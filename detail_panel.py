import json
import math
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import (
    QEvent, Qt, QTimer, QUrl,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtGui import (
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
    BLEND_EXTENSIONS,
    DATA_DIR,
    DWG_EXTENSIONS,
    EXR_EXTENSIONS,
    FBX_EXTENSIONS,
    HDR_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MAYA_SCENE_EXTENSIONS,
    OBJ_EXTENSIONS,
    PREVIEW_MAX_HEIGHT,
    PREVIEW_MIN_HEIGHT,
    PSD_EXTENSIONS,
    PUR_PREVIEW_EXTENSIONS,
    RENDERABLE_3D_EXTENSIONS,
    TEXT_PREVIEW_EXTENSIONS,
    TEXT_PREVIEW_PANEL_HEIGHT,
    TX_EXTENSIONS,
    VIDEO_EXTENSIONS,
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
    _reload_render_profiles,
    _render_log_line,
    _render_log_path,
    _set_preview_protected,
    _turntable_frames,
    _write_render_log,
    file_image_pixmap,
)
from settings_store import (
    M,
    _coerce_side_enabled,
    _sync_dynamic_M,
    load_settings,
)
from settings_widgets import (
    _MiniSlider,
    _TableFrame,
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
    human_size,
)
from capture_widgets import (
    _ColumnCard,
    _RoundedCornersEffect,
)
from preview_column import (
    _PUR_EXPORT_POOL,
    _PureRefExportTask,
    pur_embedded_image_ranges,
    pur_file_major_version,
    read_pur_embedded_image,
    read_pur_exported_image,
    read_text_preview,
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

class DetailPanel(QWidget):

    FIELDS = ["kind", "size", "modified", "path"]

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
        _sync_toggle_style(load_settings())
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
        self.well.setMinimumHeight(PREVIEW_MIN_HEIGHT)
        self.well.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.well.setStyleSheet(
            f"background: {C['well']}; border: 1px solid #282c30;"
        )
        self._preview_pixmap: QPixmap | None = None
        self._preview_request_path: str | None = None
        self._current_path: str | None = None
        self._pur_image_path: str | None = None
        self._pur_image_ranges: list[tuple[int, int, str]] = []
        self._pur_exported_images: list[str] = []
        self._pur_export_task: _PureRefExportTask | None = None
        self._pur_image_index = 0
        self._preview_generation_paths: set[str] = set()
        self._auto_preview_paths: set[str] = set()
        self._auto_preview_log_count = 0
        self.well_label = QLabel(self.well)
        self.well_label.setAlignment(Qt.AlignCenter)
        self.well_label.setStyleSheet("background: transparent; border: none;")
        self.preview_info_table = _TableFrame()
        self.preview_info_table.setFixedHeight(255)
        self._turntable_frame_paths = []
        self._turntable_frame_index = 0
        self._preview_media_preferences = {}
        self._preview_render_modes = {}
        self._turntable_timer = QTimer(self)
        self._turntable_timer.setInterval(83)
        self._turntable_timer.timeout.connect(self._advance_turntable)
        self._preview_info_cell_layouts = []
        self._preview_info_cells = []
        info_layout = QGridLayout(self.preview_info_table)
        info_layout.setContentsMargins(1, 1, 1, 1)
        info_layout.setSpacing(0)
        info_layout.setHorizontalSpacing(1)
        info_layout.setVerticalSpacing(1)
        for column in range(3):
            info_layout.setColumnStretch(column, 1)
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
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet("background: black; border: 1px solid #282c30;")
        self.video_widget.hide()
        self._video_player = QMediaPlayer(self)
        self._video_audio = QAudioOutput(self)
        self._video_audio.setMuted(True)
        self._video_player.setAudioOutput(self._video_audio)
        self._video_player.setVideoOutput(self.video_widget)
        self._video_player.setLoops(QMediaPlayer.Loops.Infinite)

        self.values: dict[str, QLabel] = {}
        self.key_labels: dict[str, QLabel] = {}
        for key in self.FIELDS:
            key_label = QLabel(key.upper())
            key_label.setObjectName("PreviewInfoHeading")
            key_label.setFont(role_font("info", 9, 600))
            self.key_labels[key] = key_label
            value = QLabel("")
            value.setObjectName("PreviewInfoValue")
            value.setFont(role_font("info", 11, 400))
            value.setWordWrap(True)
            self.values[key] = value

        def add_info_cell(key: str, row: int, column: int, column_span: int = 1):
            cell = QWidget(self.preview_info_table)
            cell.setStyleSheet(f"background: {M['table_row_a']};")
            self._preview_info_cells.append(cell)
            cell_layout = QVBoxLayout(cell)
            cell_layout.setContentsMargins(6, 3, 6, 3)
            cell_layout.setSpacing(1)
            self._preview_info_cell_layouts.append(cell_layout)
            cell_layout.addWidget(self.key_labels[key])
            cell_layout.addWidget(self.values[key])
            info_layout.addWidget(cell, row, column, 1, column_span)

        add_info_cell("kind", 0, 0)
        add_info_cell("size", 0, 1)
        add_info_cell("modified", 0, 2)
        add_info_cell("path", 1, 0)
        dimensions_cell = QWidget(self.preview_info_table)
        dimensions_cell.setStyleSheet(f"background: {M['table_row_a']};")
        self._preview_info_cells.append(dimensions_cell)
        dimensions_layout = QVBoxLayout(dimensions_cell)
        dimensions_layout.setContentsMargins(6, 3, 6, 3)
        dimensions_layout.setSpacing(1)
        self._preview_info_cell_layouts.append(dimensions_layout)
        self.preview_dimensions_heading = QLabel("DIMENSIONS · RATIO · TAILLE")
        self.preview_dimensions_heading.setObjectName("PreviewInfoHeading")
        self.preview_dimensions_heading.setFont(role_font("info", 9, 600))
        dimensions_heading_row = QHBoxLayout()
        dimensions_heading_row.setContentsMargins(0, 0, 0, 0)
        dimensions_heading_row.setSpacing(5)
        dimensions_heading_row.addWidget(self.preview_dimensions_heading)
        dimensions_heading_row.addStretch(1)
        self.preview_stale_badge = QLabel("PÉRIMÉ")
        self.preview_stale_badge.setFont(role_font("info2", 8, 700))
        self.preview_stale_badge.setToolTip("Aperçu conservé en attendant sa régénération")
        self.preview_stale_badge.setStyleSheet(
            "color: #1d1608; background: #e5b85c; border-radius: 2px; padding: 1px 5px;"
        )
        self.preview_stale_badge.hide()
        dimensions_layout.addLayout(dimensions_heading_row)
        dimensions_layout.addWidget(self.preview_dimensions_value)
        info_layout.addWidget(dimensions_cell, 1, 2)
        info_layout.setRowStretch(0, 0)
        info_layout.setRowStretch(1, 1)
        self.preview_controls_cell = QWidget(self.preview_info_table)
        self.preview_controls_cell.setStyleSheet(f"background: {M['table_row_a']};")
        self._preview_info_cells.append(self.preview_controls_cell)
        controls_layout = QVBoxLayout(self.preview_controls_cell)
        controls_layout.setContentsMargins(6, 3, 6, 3)
        controls_layout.setSpacing(3)
        self._preview_info_cell_layouts.append(controls_layout)
        self.preview_media_row = QWidget(self.preview_controls_cell)
        media_layout = QHBoxLayout(self.preview_media_row)
        media_layout.setContentsMargins(0, 0, 0, 0)
        media_layout.setSpacing(2)
        self.preview_media_group = QButtonGroup(self)
        self.preview_media_group.setExclusive(True)
        self.preview_image_button = QPushButton("Image")
        self.preview_turntable_button = QPushButton("Turntable")
        self.preview_media_buttons = {
            "image": self.preview_image_button,
            "turntable": self.preview_turntable_button,
        }
        media_button_style = (
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            "border-radius: 3px; padding: 2px; font-size: 9px; min-height: 24px; }"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
            f"QPushButton:checked {{ background: {M['accent']}; color: {M['accent_fg']}; border-color: {M['accent_border']}; }}"
        )
        for media, button in self.preview_media_buttons.items():
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(media_button_style)
            self.preview_media_group.addButton(button)
            button.clicked.connect(lambda _checked=False, selected=media: self._select_preview_media(selected))
            media_layout.addWidget(button, 1)
        self.preview_media_buttons["image"].setChecked(True)
        controls_layout.addWidget(self.preview_media_row)
        self.render_action_buttons = {}
        render_button_style = (
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            "border-radius: 3px; padding: 1px 2px; font-size: 9px; min-height: 19px; }}"
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
            controls_layout.addWidget(button)
            self.render_action_buttons[(media, mode)] = button
        controls_layout.addStretch(1)
        controls_layout.addWidget(self.preview_stale_badge, 0, Qt.AlignLeft)
        protection_row = QHBoxLayout()
        protection_row.setContentsMargins(0, 0, 0, 0)
        protection_row.setSpacing(2)
        self.render_protection_label = QLabel("PROTÉGER LE RENDU")
        self.render_protection_label.setObjectName("PreviewInfoHeading")
        self.render_protection_label.setFont(role_font("info", 8, 600))
        self.render_protection_label.setWordWrap(True)
        protection_row.addWidget(self.render_protection_toggle)
        protection_row.addWidget(self.render_protection_label)
        protection_row.addStretch(1)
        controls_layout.addLayout(protection_row)
        info_layout.addWidget(self.preview_controls_cell, 1, 1)

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
        self.preview_controls_cell.hide()
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
        content.addWidget(self.video_widget)

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

    def _stop_video(self):
        """Coupe la lecture en cours et cache le lecteur : appele avant
        toute selection (voir show_path/clear), pas seulement pour un
        fichier non-video — quitter la selection d'une video ne doit
        jamais la laisser jouer en arriere-plan, invisible."""
        if self._video_player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.video_widget.hide()

    def clear(self):
        self._turntable_timer.stop()
        self._turntable_frame_paths = []
        self.preview_controls_cell.hide()
        self._preview_request_path = None
        self._current_path = None
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
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
        self.text_preview.hide()
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
        for key_label in self.key_labels.values():
            key_label.setFont(role_font("info", 9, 600))
            key_label.setStyleSheet(
                f"color: {M['table_head_fg']}; background: transparent; border: none;"
            )
        for value in self.values.values():
            value.setFont(role_font("info2", 11, 400))
            value.setStyleSheet(
                f"color: {M['value_fg']}; background: transparent; border: none;"
            )
        self.preview_dimensions_heading.setFont(role_font("info", 9, 600))
        self.preview_dimensions_heading.setStyleSheet(
            f"color: {M['table_head_fg']}; background: transparent; border: none;"
        )
        self.preview_dimensions_value.setFont(role_font("info2", 11, 400))
        self.preview_dimensions_value.setStyleSheet(
            f"color: {M['value_fg']}; background: transparent; border: none;"
        )
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
        self.well.setStyleSheet(f"background: {C['well']}; border: 1px solid #282c30;")
        self._apply_preview_table_style()
        self.open_render_log_button.setStyleSheet(
            f"QPushButton {{ background: {C['btn']}; color: {C['text']}; border: 1px solid {C['btn_border']}; "
            f"border-radius: 3px; padding: 0 7px; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {C['btn_hover']}; border-color: {C['btn_hover_bd']}; }}"
        )
        self.refresh_fonts(True if not self.values["kind"].text() else self.values["kind"].text() == "Dossier")

    def _apply_preview_table_style(self):
        """Applique au tableau de l'inspecteur les reglages des tableaux Parametres."""
        settings = load_settings()
        colors = settings.get("colors") or {}
        _sync_dynamic_M(colors)
        self.preview_info_table.setRadius(int(settings.get("table_radius", 0)))
        border_enabled = _coerce_side_enabled(settings.get("table_border_enabled", True))
        border_colors = {
            side: resolve_color_ref(value, M["panel_border"])
            for side, value in (settings.get("table_border") or {}).items()
        }
        self.preview_info_table.setBorder(
            border_enabled, border_colors, int(settings.get("table_border_thickness", 1))
        )
        padding = settings.get("table_cell_padding") or {}
        margins = (
            max(0, int(padding.get("left", 14))),
            max(0, int(padding.get("top", 8))),
            max(0, int(padding.get("right", 14))),
            max(0, int(padding.get("bottom", 8))),
        )
        for layout in self._preview_info_cell_layouts:
            layout.setContentsMargins(*(margins if layout is not self.preview_controls_cell.layout()
                                        else (4, 3, 4, 3)))
        for cell in self._preview_info_cells:
            cell.setStyleSheet(f"background: {M['table_row_a']};")
        _sync_toggle_style(settings)
        self.render_protection_toggle.apply_style()
        heading_style = (
            f"color: {M['table_head_fg']}; background: transparent; border: none; "
            "padding: 0; font-size: 9px;"
        )
        value_style = (
            f"color: {M['value_fg']}; background: transparent; border: none; "
            "padding: 0; font-size: 11px;"
        )
        for label in self.preview_info_table.findChildren(QLabel):
            if label.objectName() == "PreviewInfoHeading":
                label.setStyleSheet(heading_style)
            elif label.objectName() == "PreviewInfoValue":
                label.setStyleSheet(value_style)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        handle = getattr(self, "_resize_handle", None)
        if handle is not None:
            handle.setGeometry(0, 0, scaled(16), self.height())
            handle.raise_()
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
        scaled = self._preview_pixmap.scaled(
            final_w, final_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.well_label.setPixmap(scaled)

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
        _reload_render_profiles()
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

    def _navigate_pur_image(self, step: int):
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
        if self.text_preview.isVisible() or self.video_widget.isVisible():
            if not automatic:
                return
            self.text_preview.hide()
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
        if self.text_preview.isVisible() or self.video_widget.isVisible():
            if path_str not in self._auto_preview_paths:
                return
            self.text_preview.hide()
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
        self._refresh_render_action_buttons()
        was_requested = path_str == self._preview_request_path or path_str in self._preview_generation_paths
        self._preview_generation_paths.discard(path_str)
        self._auto_preview_paths.discard(path_str)
        path = Path(path_str)
        try:
            still_current_file = path.stat().st_mtime == mtime
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
                    widget.viewport().update()
        selected_mode = self._preview_render_modes.get((path_str, "image"), "low")
        show_result = completed_mode == selected_mode or path.suffix.lower() not in RENDERABLE_3D_EXTENSIONS
        if (self._preview_request_path == path_str or self._current_path == path_str) and show_result:
            if pix is None and path_str in _STALE_PREVIEW_PATHS and still_current_file:
                pix, _is_stale = _read_preview_pixmap(path, mtime)
            self._preview_request_path = None
            if pix is not None and path.suffix.lower() in IMAGE_EXTENSIONS:
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
            if not self.text_preview.isVisible() and not self.video_widget.isVisible():
                completion_percent = 100 if pix is not None else 0
                completion_message = "Aperçu terminé" if pix is not None else "Aperçu indisponible"
                self.preview_log.appendPlainText(
                    _render_log_line(f"[{completion_percent:3d}%] {path.name} — {completion_message}")
                )
                self.preview_log.ensureCursorVisible()
            return
        if not self.text_preview.isVisible() and not self.video_widget.isVisible():
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

    def show_path(self, path: Path):
        self._turntable_timer.stop()
        self.turntable_play_button.setText("▶")
        self._turntable_frame_paths = []
        self._current_path = str(path)
        self._refresh_render_action_buttons()
        supports_turntable = not path.is_dir() and path.suffix.lower() in TURNTABLE_EXTENSIONS
        self.preview_controls_cell.setVisible(supports_turntable)
        preferred_media = self._preview_media_preferences.get(str(path), "image")
        self.preview_media_buttons.get(preferred_media, self.preview_image_button).setChecked(True)
        self.turntable_controls.setVisible(supports_turntable and preferred_media == "turntable")
        self._update_turntable_control_state(False)
        self._pur_image_path = None
        self._pur_image_ranges = []
        self._pur_exported_images = []
        self._pur_image_index = 0
        self.pur_navigation.hide()
        self.name.setText(path.name)
        is_renderable_3d = not path.is_dir() and path.suffix.lower() in RENDERABLE_3D_EXTENSIONS
        self.render_protection_toggle.blockSignals(True)
        self.render_protection_toggle.setChecked(
            is_renderable_3d and _is_preview_protected(path)
        )
        self.render_protection_toggle.blockSignals(False)
        self.render_protection_toggle.setVisible(is_renderable_3d)
        is_dir = path.is_dir()
        self.name.setFont(role_font("folders" if is_dir else "files", 12, 600, tracking=0.12))
        self.name.setStyleSheet(
            f"color: {role_color('folders' if is_dir else 'files', C['text'])}; background: transparent;"
        )
        self._preview_pixmap = None
        self._preview_request_path = None
        self.preview_stale_badge.hide()
        self.preview_progress.hide()
        if self._preview_generation_paths:
            self.preview_log.show()
            self.well_label.hide()
        else:
            self.preview_log.hide()
            self.well_label.show()
        self._stop_video()
        is_text_preview = not is_dir and path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS
        is_video = not is_dir and path.suffix.lower() in VIDEO_EXTENSIONS
        if is_video:
            # Lecture reelle (voir _stop_video/video_widget), pas la frame
            # figee de file_image_pixmap : celle-ci ne sert plus ici qu'a
            # dimensionner le lecteur avant que la premiere image ne soit
            # decodee (voir _show_video). well/text_preview jamais affiches
            # en meme temps.
            self.well.hide()
            self.text_preview.hide()
            self._show_video(path)
        elif is_text_preview:
            # Extrait de contenu (voir read_text_preview) plutot que le
            # "well" image : les deux ne s'affichent jamais ensemble.
            self.well.hide()
            content_text = read_text_preview(path)
            self.text_preview.setPlainText(content_text if content_text is not None else "(apercu indisponible)")
            self.text_preview.show()
        else:
            self.text_preview.hide()
            self.well.show()
            if not is_dir:
                suffix = path.suffix.lower()
                if suffix in IMAGE_EXTENSIONS:
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        mtime = None
                    stale_pix = None
                    is_stale = False
                    if mtime is not None:
                        stale_pix, is_stale = _read_preview_pixmap(path, mtime)
                    if is_stale and stale_pix is not None:
                        self._preview_pixmap = stale_pix
                        file_image_pixmap(path)  # auto-régénère les caches 2D périmés
                    else:
                        pix = QPixmap(str(path))
                        if not pix.isNull():
                            self._preview_pixmap = pix
                        file_image_pixmap(path)  # crée le cache 2D manquant
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
                elif suffix in (BLEND_EXTENSIONS | MAYA_SCENE_EXTENSIONS | FBX_EXTENSIONS):
                    if str(path) in _MANUAL_3D_PREVIEW_REQUESTS:
                        _MANUAL_3D_PREVIEW_REQUESTS.discard(str(path))
                        render_mode = _MANUAL_3D_PREVIEW_MODE.pop(str(path), "low")
                        self._preview_render_modes[(str(path), "image")] = render_mode
                        _cached_file_image_pixmap(path)
                        self._start_3d_preview(path, render_mode)
                    else:
                        self._preview_pixmap = _cached_file_image_pixmap(
                            path, self._preview_render_modes.get((str(path), "image"), "low"))
                elif suffix in DWG_EXTENSIONS:
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
                        if is_pur_v2:
                            self.pur_image_counter.setText("Extraction des images PureRef…")
                            self.pur_next_button.setEnabled(False)
                            if mtime is not None:
                                self._start_pur_export(path, mtime)
                        if self._pur_image_ranges:
                            self._navigate_pur_image(0)
                        else:
                            self.well_label.setText("Extraction des images PureRef en cours…")
                    else:
                        self.well_label.setText("Aucune image intégrée lisible dans ce fichier PureRef.")
                elif (suffix in PSD_EXTENSIONS
                      or suffix in EXR_EXTENSIONS or suffix in HDR_EXTENSIONS
                      or suffix in TX_EXTENSIONS):
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
        try:
            info = path.stat()
            modified = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            info, modified = None, "-"
        if path.is_dir():
            kind = "Dossier"
            size = f"{count_entries(path)} elements"
        else:
            kind = (path.suffix[1:].upper() + " file") if path.suffix else "Fichier"
            size = human_size(info.st_size) if info else "-"
        self.values["kind"].setText(kind)
        self.values["size"].setText(size)
        self.values["modified"].setText(modified)
        self.values["path"].setText(str(path))
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

WINDOW_STATE_PATH = DATA_DIR / "pipeline_window_state.json"

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
