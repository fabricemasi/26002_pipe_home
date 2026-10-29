"""Façade des services du navigateur : voir la carte docs/agents/colonnes.md.

Pour modifier un état ou patcher un appel, viser le module qui le porte.
"""

import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QPainter,
    QPen,
    QPixmap,
    QPolygon,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
    QWidget,
)
from app_style import (
    C,
    COLUMN_TYPE_OVERRIDE_KEYS,
    INSPECTOR_TITLE,
    PREVIEW_STACK_TITLE,
    custom_softwares,
    removed_softwares,
    set_custom_softwares,
    set_removed_softwares,
    font,
    role_font,
    scaled,
    set_auto_collapse_set_columns,
    set_button_frame,
    set_button_radius,
    set_control_look,
    set_color,
    set_column_gap,
    set_columns_resizable,
    set_header_style,
    set_input_frame,
    set_input_radius,
    set_role_font,
    set_table_radius,
    set_ui_scale,
    resolve_color_ref,
    set_general_column_style,
    set_column_style,
    column_style_for,
    ITEM_FONT_ROLE_LABELS,
)
import ui_state
from config import (
    FLATTEN_FOLDERS,
    HIDDEN_PREFIXES,
    ICONS_DIR,
    SOFTWARE_COLUMN_LABEL,
    THUMBNAIL_FILENAME,
    THUMBNAIL_MAX_DIM,
)
from previews import (
    cached_mtime as _previews_mtime,
    forget_mtime as _forget_mtime,
)
from previews import (
    SOFTWARE_ICONS,
    UI_ICON_FILE_DEFAULT,
    UI_ICON_FOLDER_DEFAULT,
    UI_ICON_PIN_ACTIVE,
    UI_ICON_PIN_INACTIVE,
    _FALLBACK_SOFTWARE_BADGE_PALETTE,
    _bounded_cache_set,
    _clear_hidden,
    _contain_square,
    _set_hidden,
    _smooth_scale_down,
    _software_icon_cache,
    custom_software_icon_path,
    custom_ui_icon_pixmap,
)
from config import (
    GLOBAL_OMIT_DIR_NAMES,
    GLOBAL_OMIT_FILE_EXTENSIONS,
    GLOBAL_OMIT_FILE_NAMES,
)
from settings_store import (
    _coerce_side_enabled,
    _load_presets,
    _save_presets,
    _sync_slider_style,
    load_settings,
    save_settings,
)
from settings_widgets import (
    DRAG_GHOST_OPACITY,
    _paint_bordered_rect,
    _radius_any,
    _radius_dict,
    _rounded_rect_path,
    ShadowUnderlay,
    paint_shadow,
    shadow_look,
)



#!/usr/bin/env python3
"""
Pipeline Browser - navigateur en colonnes (Miller columns) pour F:\\PIPELINE.

Habillage base sur la maquette Claude Design :
  IBM Plex Sans / IBM Plex Mono, fond #1a1c1e, accent #3f6f9f,
  colonnes de 220px, lignes de 24px, barre de statut monospace.

Lecture seule pour l'instant.

    pip install PySide6
    pythonw pipeline_browser.py   (pythonw = sans fenetre console ; python = avec)
"""

if sys.platform == "win32":
    # Sans cette declaration, Windows ne sait pas que l'appli gere elle-meme
    # le DPI par moniteur : des qu'une fenetre s'etend sur plusieurs ecrans
    # d'echelle differente (125% + 100% par ex.), il applique lui-meme un
    # zoom bitmap sur la portion affichee sur l'ecran le moins dense, d'ou
    # l'effet de flou/pixelisation - independant de tout ce que l'appli
    # dessine. Doit etre appele avant la creation de la QApplication.
    import ctypes
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 (Windows 10 1703+) :
        # rendu natif par moniteur, aucun etirement par l'OS.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

# Dependances optionnelles (voir requirements.txt) : import protege pour
# qu'une install sans ces paquets perde juste les apercus concernes, sans
# empecher l'appli de demarrer. numpy sert au rasteriseur des .obj
# (voir _rasterize_obj_numpy) ET, avec OpenEXR, au decodage des .exr (voir
# _decode_exr_image) — verifie separement, un .obj lisse ne doit pas
# dependre de la presence d'OpenEXR.
try:
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    _OPENEXR_AVAILABLE = _NUMPY_AVAILABLE
except ImportError:
    _OPENEXR_AVAILABLE = False


from browser_core_parts.scan import (
    _is_globally_omitted_file,
    _is_globally_omitted_dir,
    _is_globally_omitted_path,
    human_size,
    _ENTRY_INFO,
    _LISTED_COUNT,
    _DIR_CHILDREN,
    _remote_gui,
    _request_directory,
    remember_entry,
    entry_mtime,
    listed_count,
    entry_is_dir,
    entry_size,
    CONFIG_FRESH_S,
    _CONFIG_PREFIX,
    _DIR_CONFIG,
    _CONFIG_STAT,
    _CONFIG_TEXT,
    _note_dir_config,
    config_state,
    read_config_text,
    forget_config,
    forget_all_config,
    list_entries,
)

from browser_core_parts.icons import (
    _fallback_software_badge_style,
    _generate_software_badge,
    software_choices,
    software_icon_pixmap,
    _row_icon_pixmap,
    _PIN_ICON_CACHE,
    _pin_icon_pixmap,
    project_thumbnail_path,
    _project_thumbnail_cache,
    has_project_thumbnail,
    project_thumbnail_pixmap,
    default_thumbnail,
)

from browser_core_parts.dimensions import (
    COLUMN_MIN_WIDTH,
    COLUMN_MAX_WIDTH,
    COLUMN_RESIZE_MARGIN,
    GROUP_COLUMN_DEFAULT_HEIGHT,
    GROUP_COLUMN_MIN_HEIGHT,
    GROUP_COLUMN_MAX_HEIGHT,
    _WIDGET_SIZE_MAX,
    ROW_RESIZE_MIN_HEIGHT,
    ROW_RESIZE_MAX_HEIGHT,
    STATUS_HEIGHT,
    TITLEBAR_HEIGHT,
    DETAIL_PANEL_MIN_WIDTH,
    DETAIL_PANEL_MAX_WIDTH,
    COLUMN_SETTINGS,
    _ITEM_FONT_LABEL_TO_ROLE,
    _col_key,
    col_width,
    col_row_height,
    col_plain_height,
    col_spacing,
    col_img_pad,
)

from browser_core_parts.status import (
    STATUS_FOLDERS,
    _STATUS_FOLDER_SET,
    _dir_has_content,
    status_folder_state,
    SOFTS_FOLDER_NAME,
    _named_subdir,
    _softs_subdir,
    _count_dirs_recursive,
    count_entries,
)

from browser_core_parts.capture import (
    _translucent_grab,
    _make_group_drag_ghost,
    SquareCaptureOverlay,
    MultiScreenCapture,
)

from browser_core_parts.project_config import (
    PROJECT_COLUMNS_FILENAME,
    PROJECT_COLUMNS_DEFAULTS_FILENAME,
    WORK_DIR_TYPES,
    DEFAULT_WORK_DIR_TYPE,
    _project_columns_path,
    _project_columns_defaults_path,
    _coerce_project_column,
    _coerce_work_dir,
    _PROJECT_COLUMNS_CACHE,
    _PROJECT_LIGHTROOM_CACHE,
    _lightroom_set_defaults,
    invalidate_project_columns_cache,
    _lightroom_default_project_config,
    _read_project_columns,
    load_project_columns,
    save_project_columns_defaults,
    save_project_columns,
    project_step_count,
    LAYOUT_SETTINGS_FILENAME,
    _layout_settings_path,
    PIN_LAYOUT_KEYS,
    _BY_PRESET,
    _layout_preset,
    _read_layout_raw,
    load_layout_settings,
    save_layout_settings,
    _update_layout_setting,
    SHORTCUTS_FILENAME,
    _shortcuts_path,
    load_shortcuts,
    save_shortcuts,
    add_shortcut,
    remove_shortcut,
)

from browser_core_parts.row_paint import (
    _step_badge_color,
    _step_badge_text_color,
    _row_preview_left_x,
    _step_badge_rect,
    ROLE_PATH,
    ROLE_ISDIR,
    ROLE_META,
    ROLE_SOURCE_LABEL,
    ROLE_SOURCE_STEP,
    ROLE_IS_SHORTCUT,
    ROLE_LIGHTROOM_SHORTCUT,
    ROLE_MEDIA_COUNTS,
    ROLE_SPACE_ABOVE,
    ROLE_TITLE_ABOVE,
    ROLE_SPACE_BELOW,
    ROLE_PIN_BOTTOM,
    ROLE_BOTTOM_GAP,
    ITEM_TITLE_DEFAULT_STYLE,
    item_title_style,
    item_title_font,
    item_title_min_height,
    paint_item_title,
    _paint_row_border,
    _IMAGE_MASK_CACHE,
    _IMAGE_MASK_CACHE_MAX,
    _rounded_mask_pixmap,
    _ROW_IMAGE_CACHE,
    _ROW_IMAGE_CACHE_MAX,
    _row_image_pixmap,
    _paint_row_image,
    _resolve_font_family,
    _resolve_row_font_color,
    _resolve_shortcut_font_color,
)

from browser_core_parts.settings import (
    _resize_width_indicator,
    _refresh_resize_width_style,
    _show_resize_width,
    _hide_resize_width,
    _show_row_resize_indicator,
    _live_dialog_values,
    _persist_row_height,
    _sync_default_preset_override,
    _persist_column_width,
    _persist_detail_panel_width,
    _register_settings_hooks,
    apply_all_settings,
)

from browser_core_parts.system_ui import (
    open_path,
    open_in_file_manager,
    reveal_in_file_manager,
    _prompt_change_thumbnail,
    _prompt_capture_thumbnail,
    _save_thumbnail_pixmap_for,
    _prompt_reset_thumbnail,
)

from browser_core_parts.animation import (
    _HoverPrime,
    _GIL_USERS,
    _SWITCH_INTERVAL,
    _snappy_gil,
    _fine_timer,
    _FadeOverlay,
    _SlideOverlay,
)

from browser_core_parts import scan as _scan, icons as _icons

_DYNAMIC_OWNERS = {
    '_CONFIG_REVISION': _scan,
    '_default_thumbnail': _icons,
}

__all__ = [
    'json', 'os', 'subprocess', 'sys', 'time',
    'threading', 'Path', 'TYPE_CHECKING', 'QElapsedTimer', 'QEvent',
    'QObject', 'QPoint', 'QRect', 'QSize', 'Qt',
    'QTimer', 'QUrl', 'Signal', 'QColor', 'QCursor',
    'QDesktopServices', 'QPainter', 'QPen', 'QPixmap', 'QPolygon',
    'QRegion', 'QApplication', 'QFileDialog', 'QLabel', 'QMessageBox',
    'QWidget', 'C', 'COLUMN_TYPE_OVERRIDE_KEYS', 'INSPECTOR_TITLE', 'PREVIEW_STACK_TITLE',
    'custom_softwares', 'removed_softwares', 'set_custom_softwares', 'set_removed_softwares', 'font',
    'role_font', 'scaled', 'set_auto_collapse_set_columns', 'set_button_frame', 'set_button_radius',
    'set_control_look', 'set_color', 'set_column_gap', 'set_columns_resizable', 'set_header_style',
    'set_input_frame', 'set_input_radius', 'set_role_font', 'set_table_radius', 'set_ui_scale',
    'resolve_color_ref', 'set_general_column_style', 'set_column_style', 'column_style_for', 'ITEM_FONT_ROLE_LABELS',
    'ui_state', 'FLATTEN_FOLDERS', 'HIDDEN_PREFIXES', 'ICONS_DIR', 'SOFTWARE_COLUMN_LABEL',
    'THUMBNAIL_FILENAME', 'THUMBNAIL_MAX_DIM', '_previews_mtime', '_forget_mtime', 'SOFTWARE_ICONS',
    'UI_ICON_FILE_DEFAULT', 'UI_ICON_FOLDER_DEFAULT', 'UI_ICON_PIN_ACTIVE', 'UI_ICON_PIN_INACTIVE', '_FALLBACK_SOFTWARE_BADGE_PALETTE',
    '_bounded_cache_set', '_clear_hidden', '_contain_square', '_set_hidden', '_smooth_scale_down',
    '_software_icon_cache', 'custom_software_icon_path', 'custom_ui_icon_pixmap', 'GLOBAL_OMIT_DIR_NAMES', 'GLOBAL_OMIT_FILE_EXTENSIONS',
    'GLOBAL_OMIT_FILE_NAMES', '_coerce_side_enabled', '_load_presets', '_save_presets', '_sync_slider_style',
    'load_settings', 'save_settings', 'DRAG_GHOST_OPACITY', '_paint_bordered_rect', '_radius_any',
    '_radius_dict', '_rounded_rect_path', 'ShadowUnderlay', 'paint_shadow', 'shadow_look',
    '_NUMPY_AVAILABLE', '_OPENEXR_AVAILABLE', '_is_globally_omitted_file', '_is_globally_omitted_dir', '_is_globally_omitted_path',
    'human_size', '_ENTRY_INFO', '_LISTED_COUNT', '_DIR_CHILDREN', '_remote_gui',
    '_request_directory', 'remember_entry', 'entry_mtime', 'listed_count', 'entry_is_dir',
    'entry_size', 'CONFIG_FRESH_S', '_CONFIG_PREFIX', '_DIR_CONFIG', '_CONFIG_STAT',
    '_CONFIG_TEXT', '_note_dir_config', 'config_state', 'read_config_text', 'forget_config',
    'forget_all_config', 'list_entries', '_fallback_software_badge_style', '_generate_software_badge', 'software_choices',
    'software_icon_pixmap', '_row_icon_pixmap', '_PIN_ICON_CACHE', '_pin_icon_pixmap', 'project_thumbnail_path',
    '_project_thumbnail_cache', 'has_project_thumbnail', 'project_thumbnail_pixmap', 'default_thumbnail', 'COLUMN_MIN_WIDTH',
    'COLUMN_MAX_WIDTH', 'COLUMN_RESIZE_MARGIN', 'GROUP_COLUMN_DEFAULT_HEIGHT', 'GROUP_COLUMN_MIN_HEIGHT', 'GROUP_COLUMN_MAX_HEIGHT',
    '_WIDGET_SIZE_MAX', 'ROW_RESIZE_MIN_HEIGHT', 'ROW_RESIZE_MAX_HEIGHT', 'STATUS_HEIGHT', 'TITLEBAR_HEIGHT',
    'DETAIL_PANEL_MIN_WIDTH', 'DETAIL_PANEL_MAX_WIDTH', 'COLUMN_SETTINGS', '_ITEM_FONT_LABEL_TO_ROLE', '_col_key',
    'col_width', 'col_row_height', 'col_plain_height', 'col_spacing', 'col_img_pad',
    'STATUS_FOLDERS', '_STATUS_FOLDER_SET', '_dir_has_content', 'status_folder_state', 'SOFTS_FOLDER_NAME',
    '_named_subdir', '_softs_subdir', '_count_dirs_recursive', 'count_entries', '_translucent_grab',
    '_make_group_drag_ghost', 'SquareCaptureOverlay', 'MultiScreenCapture', 'PROJECT_COLUMNS_FILENAME', 'PROJECT_COLUMNS_DEFAULTS_FILENAME',
    'WORK_DIR_TYPES', 'DEFAULT_WORK_DIR_TYPE', '_project_columns_path', '_project_columns_defaults_path', '_coerce_project_column',
    '_coerce_work_dir', '_PROJECT_COLUMNS_CACHE', '_PROJECT_LIGHTROOM_CACHE', '_lightroom_set_defaults', 'invalidate_project_columns_cache',
    '_lightroom_default_project_config', '_read_project_columns', 'load_project_columns', 'save_project_columns_defaults', 'save_project_columns',
    'project_step_count', 'LAYOUT_SETTINGS_FILENAME', '_layout_settings_path', 'PIN_LAYOUT_KEYS', '_BY_PRESET',
    '_layout_preset', '_read_layout_raw', 'load_layout_settings', 'save_layout_settings', '_update_layout_setting',
    'SHORTCUTS_FILENAME', '_shortcuts_path', 'load_shortcuts', 'save_shortcuts', 'add_shortcut',
    'remove_shortcut', '_step_badge_color', '_step_badge_text_color', '_row_preview_left_x', '_step_badge_rect',
    'ROLE_PATH', 'ROLE_ISDIR', 'ROLE_META', 'ROLE_SOURCE_LABEL', 'ROLE_SOURCE_STEP',
    'ROLE_IS_SHORTCUT', 'ROLE_LIGHTROOM_SHORTCUT', 'ROLE_MEDIA_COUNTS', 'ROLE_SPACE_ABOVE', 'ROLE_TITLE_ABOVE',
    'ROLE_SPACE_BELOW', 'ROLE_PIN_BOTTOM', 'ROLE_BOTTOM_GAP', 'ITEM_TITLE_DEFAULT_STYLE', 'item_title_style',
    'item_title_font', 'item_title_min_height', 'paint_item_title', '_paint_row_border', '_IMAGE_MASK_CACHE',
    '_IMAGE_MASK_CACHE_MAX', '_rounded_mask_pixmap', '_ROW_IMAGE_CACHE', '_ROW_IMAGE_CACHE_MAX', '_row_image_pixmap',
    '_paint_row_image', '_resolve_font_family', '_resolve_row_font_color', '_resolve_shortcut_font_color', '_resize_width_indicator',
    '_refresh_resize_width_style', '_show_resize_width', '_hide_resize_width', '_show_row_resize_indicator', '_live_dialog_values',
    '_persist_row_height', '_sync_default_preset_override', '_persist_column_width', '_persist_detail_panel_width', '_register_settings_hooks',
    'apply_all_settings', 'open_path', 'open_in_file_manager', 'reveal_in_file_manager', '_prompt_change_thumbnail',
    '_prompt_capture_thumbnail', '_save_thumbnail_pixmap_for', '_prompt_reset_thumbnail', '_HoverPrime', '_GIL_USERS',
    '_SWITCH_INTERVAL', '_snappy_gil', '_fine_timer', '_FadeOverlay', '_SlideOverlay',
]

def __getattr__(name):
    module = _DYNAMIC_OWNERS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(module, name)


def __dir__():
    return sorted(set(globals()) | _DYNAMIC_OWNERS.keys())
