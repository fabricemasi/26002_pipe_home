"""Façade des services d’aperçus (carte : docs/agents/apercus.md).

Lecture et appels par previews.X conservés. Pour réaffecter un état ou patcher
un nom, viser son module propriétaire dans preview_services (voir la carte).
Les états réaffectés sont lus dynamiquement, sans copie figée dans cette façade.
"""

from config import TWO_D_IMAGE_EXTENSIONS as TWO_D_IMAGE_EXTENSIONS

from preview_services.optional import (
    _NUMPY_AVAILABLE as _NUMPY_AVAILABLE,
    _RAWPY_AVAILABLE as _RAWPY_AVAILABLE,
    _OPENEXR_AVAILABLE as _OPENEXR_AVAILABLE,
)
from preview_services.filesystem import (
    _set_hidden as _set_hidden,
    _FILE_ATTRIBUTE_NORMAL as _FILE_ATTRIBUTE_NORMAL,
    _clear_hidden as _clear_hidden,
)
from preview_services.mtime import (
    _MTIME_CACHE as _MTIME_CACHE,
    _MTIME_TTL as _MTIME_TTL,
    _MEMORY_ONLY as _MEMORY_ONLY,
    _MTIME_PENDING as _MTIME_PENDING,
    _MTIME_PENDING_LOCK as _MTIME_PENDING_LOCK,
    _MtimeSignals as _MtimeSignals,
    MTIME_SIGNALS as MTIME_SIGNALS,
    memory_only as memory_only,
    requests_held as requests_held,
    _refresh_mtimes as _refresh_mtimes,
    _queue_mtime as _queue_mtime,
    _REMOTE_DRIVES as _REMOTE_DRIVES,
    is_remote_path as is_remote_path,
    cached_mtime as cached_mtime,
    forget_mtime as forget_mtime,
)
from preview_services.pixmaps import (
    _smooth_scale_down as _smooth_scale_down,
    _contain_square as _contain_square,
    _cover_crop_rect as _cover_crop_rect,
)
from preview_services.icons import (
    SOFTWARE_ICONS as SOFTWARE_ICONS,
    _software_icon_cache as _software_icon_cache,
    software_icon_key as software_icon_key,
    custom_software_icon_path as custom_software_icon_path,
    UI_ICON_FOLDER_DEFAULT as UI_ICON_FOLDER_DEFAULT,
    UI_ICON_FILE_DEFAULT as UI_ICON_FILE_DEFAULT,
    UI_ICON_PIN_INACTIVE as UI_ICON_PIN_INACTIVE,
    UI_ICON_PIN_ACTIVE as UI_ICON_PIN_ACTIVE,
    UI_ICON_SETTINGS_GEAR as UI_ICON_SETTINGS_GEAR,
    UI_ICON_SETTINGS_STYLE as UI_ICON_SETTINGS_STYLE,
    UI_ICON_APP_LOGO as UI_ICON_APP_LOGO,
    UI_ICON_NAVBAR_MIN as UI_ICON_NAVBAR_MIN,
    UI_ICON_NAVBAR_MAX as UI_ICON_NAVBAR_MAX,
    UI_ICON_NAVBAR_CLOSE as UI_ICON_NAVBAR_CLOSE,
    UI_ICON_NAVBAR_BROWSE as UI_ICON_NAVBAR_BROWSE,
    UI_ICON_NAVBAR_PRESETS as UI_ICON_NAVBAR_PRESETS,
    UI_ICON_NAVBAR_CRUMB_SEPARATOR as UI_ICON_NAVBAR_CRUMB_SEPARATOR,
    UI_ICON_NAVBAR_VIEWER as UI_ICON_NAVBAR_VIEWER,
    UI_ICON_NAVBAR_TEXT_EDITOR as UI_ICON_NAVBAR_TEXT_EDITOR,
    UI_ICON_NAVBAR_BOARD as UI_ICON_NAVBAR_BOARD,
    UI_ICON_COLLAPSE_TOGGLE as UI_ICON_COLLAPSE_TOGGLE,
    UI_ICON_SHORTCUT as UI_ICON_SHORTCUT,
    UI_ICON_VIEWER_HIDE as UI_ICON_VIEWER_HIDE,
    UI_ICON_VIEWER_SHOW as UI_ICON_VIEWER_SHOW,
    UI_ICON_VIEWER_GALLERY as UI_ICON_VIEWER_GALLERY,
    UI_ICON_VIEWER_SINGLE as UI_ICON_VIEWER_SINGLE,
    UI_ICON_VIEWER_FILTER as UI_ICON_VIEWER_FILTER,
    UI_ICON_VIEWER_STAR_ON as UI_ICON_VIEWER_STAR_ON,
    UI_ICON_VIEWER_STAR_OFF as UI_ICON_VIEWER_STAR_OFF,
    UI_ICON_VIEWER_FLAG_KEEP as UI_ICON_VIEWER_FLAG_KEEP,
    UI_ICON_VIEWER_FLAG_DELETE as UI_ICON_VIEWER_FLAG_DELETE,
    UI_ICON_VIEWER_PLUS as UI_ICON_VIEWER_PLUS,
    UI_ICON_VIEWER_RECURSIVE as UI_ICON_VIEWER_RECURSIVE,
    VIEWER_BUTTON_ICONS as VIEWER_BUTTON_ICONS,
    VIEWER_ICON_KEYS as VIEWER_ICON_KEYS,
    _UI_ICON_CACHE as _UI_ICON_CACHE,
    custom_ui_icon_pixmap as custom_ui_icon_pixmap,
    _FALLBACK_SOFTWARE_BADGE_PALETTE as _FALLBACK_SOFTWARE_BADGE_PALETTE,
)
from preview_services.memory import (
    _CACHE_MAX_ENTRIES as _CACHE_MAX_ENTRIES,
    _bounded_cache_set as _bounded_cache_set,
    _file_image_cache as _file_image_cache,
    _file_image_high_cache as _file_image_high_cache,
    _file_image_column_cache as _file_image_column_cache,
    _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM as _FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM,
    _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES as _FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES,
    _FILE_IMAGE_COLUMN_LOOKUP_MISSES as _FILE_IMAGE_COLUMN_LOOKUP_MISSES,
    _cache_file_preview as _cache_file_preview,
    _PREVIEW_STALE_LOOKUP_MISSES as _PREVIEW_STALE_LOOKUP_MISSES,
)
from preview_services.abr import (
    _ABR_MAX_BRUSHES as _ABR_MAX_BRUSHES,
    _ABR_SAMPLE_MAX_DIM as _ABR_SAMPLE_MAX_DIM,
    _abr_unpackbits as _abr_unpackbits,
    _abr_read_sample as _abr_read_sample,
    _abr_brushes as _abr_brushes,
    _abr_desc_order as _abr_desc_order,
    _decode_abr_image as _decode_abr_image,
)
from preview_services.dwg import (
    _oda_environment as _oda_environment,
    _oda_file_converter as _oda_file_converter,
    _DWG_THUMBNAIL_SENTINEL as _DWG_THUMBNAIL_SENTINEL,
    _decode_dwg_thumbnail as _decode_dwg_thumbnail,
    _decode_dwg_image as _decode_dwg_image,
    _render_dxf_file as _render_dxf_file,
    _render_dwg_with_oda as _render_dwg_with_oda,
)
from preview_services.font import (
    _FONT_RENDER_LOCK as _FONT_RENDER_LOCK,
    _decode_font_image as _decode_font_image,
)
from preview_services.pdf import (
    pdf_page_count as pdf_page_count,
    _render_pdf_page as _render_pdf_page,
    ai_has_pdf_content as ai_has_pdf_content,
    _decode_ai_xmp_thumbnail as _decode_ai_xmp_thumbnail,
    _decode_ai_image as _decode_ai_image,
)
from preview_services.images import (
    _decode_psd_thumbnail as _decode_psd_thumbnail,
    _oiiotool_executable as _oiiotool_executable,
    _decode_tx_image as _decode_tx_image,
    _decode_exr_image as _decode_exr_image,
    _LUT_CURVE_NAMES as _LUT_CURVE_NAMES,
    lut_image_kind as lut_image_kind,
    lut_curve_choices as lut_curve_choices,
    _lut_default_curve as _lut_default_curve,
    _GAMUT_PRIMARIES as _GAMUT_PRIMARIES,
    _D65 as _D65,
    _CURVE_GAMUT as _CURVE_GAMUT,
    _rgb_to_xyz as _rgb_to_xyz,
    _log_encode as _log_encode,
    _raw_linear_in_gamut as _raw_linear_in_gamut,
    _encode_8bit_as_log as _encode_8bit_as_log,
    lut_test_image_for as lut_test_image_for,
    _decode_raw_log_image as _decode_raw_log_image,
    _lut_test_image_signature as _lut_test_image_signature,
    set_lut_test_images as set_lut_test_images,
    _parse_cube_lut as _parse_cube_lut,
    _apply_cube_lut as _apply_cube_lut,
    _lut_test_image as _lut_test_image,
    _decode_cube_image as _decode_cube_image,
    _decode_raw_image as _decode_raw_image,
    _decode_embedded_jpeg as _decode_embedded_jpeg,
    _decode_hdr_image as _decode_hdr_image,
    _decode_2d_image as _decode_2d_image,
)
from preview_services.profiles import (
    OBJ_PREVIEW_MAX_TRIANGLES as OBJ_PREVIEW_MAX_TRIANGLES,
    OBJ_PREVIEW_RENDER_EDGES as OBJ_PREVIEW_RENDER_EDGES,
    OBJ_PREVIEW_DIM as OBJ_PREVIEW_DIM,
    RENDER_PARAMETERS_PATH as RENDER_PARAMETERS_PATH,
    _render_value as _render_value,
    _load_render_profiles as _load_render_profiles,
    RENDER_PROFILES_SNAPSHOT as RENDER_PROFILES_SNAPSHOT,
    _write_profiles_snapshot as _write_profiles_snapshot,
    _initial_render_profiles as _initial_render_profiles,
    _reload_render_profiles as _reload_render_profiles,
    _begin_automatic_render_batch as _begin_automatic_render_batch,
    _render_profile as _render_profile,
    _apply_render_background as _apply_render_background,
)
from preview_services.cache import (
    FILE_IMAGE_CACHE_MAX_DIM as FILE_IMAGE_CACHE_MAX_DIM,
    FILE_IMAGE_DISK_CACHE_DIR as FILE_IMAGE_DISK_CACHE_DIR,
    AUTO_RENDER_ENABLED as AUTO_RENDER_ENABLED,
    IMAGE_DISK_CACHE_ENABLED as IMAGE_DISK_CACHE_ENABLED,
    _IMAGE_CACHE_SUFFIXES as _IMAGE_CACHE_SUFFIXES,
    _PREVIEW_CACHE_VERSION as _PREVIEW_CACHE_VERSION,
    _TURNTABLE_CACHE_VERSION as _TURNTABLE_CACHE_VERSION,
    TURNTABLE_FRAME_COUNT as TURNTABLE_FRAME_COUNT,
    TURNTABLE_EXTENSIONS as TURNTABLE_EXTENSIONS,
    _cache_slug as _cache_slug,
    _cache_label as _cache_label,
    _cache_digest_of as _cache_digest_of,
    _cache_glob as _cache_glob,
    _CacheDirIndex as _CacheDirIndex,
    _CACHE_INDEX as _CACHE_INDEX,
    _turntable_cache_path as _turntable_cache_path,
    _turntable_metadata_path as _turntable_metadata_path,
    _turntable_work_path as _turntable_work_path,
    _turntable_frames as _turntable_frames,
    _PREVIEW_PROTECTION_FILE as _PREVIEW_PROTECTION_FILE,
    _protected_preview_paths as _protected_preview_paths,
    _is_preview_protected as _is_preview_protected,
    _set_preview_protected as _set_preview_protected,
    _file_image_cache_signature as _file_image_cache_signature,
    _file_image_cache_path as _file_image_cache_path,
    _preview_cache_metadata_path as _preview_cache_metadata_path,
    delete_preview_cache as delete_preview_cache,
    _keep_cache_digests as _keep_cache_digests,
    prune_unused_previews as prune_unused_previews,
    sweep_preview_cache as sweep_preview_cache,
    _SWEEP_YIELD_S as _SWEEP_YIELD_S,
    SWEEP_INTERVAL_S as SWEEP_INTERVAL_S,
    sweep_preview_cache_if_due as sweep_preview_cache_if_due,
    migrate_cache_names as migrate_cache_names,
    _record_preview_cache as _record_preview_cache,
    _preview_cache_metadata_matches as _preview_cache_metadata_matches,
    _find_stale_preview_cache as _find_stale_preview_cache,
    _prune_stale_disk_cache as _prune_stale_disk_cache,
)
from preview_services.render_log import (
    _render_log_line as _render_log_line,
    _render_log_path as _render_log_path,
    _RENDER_LOG_LOCK as _RENDER_LOG_LOCK,
    _update_render_log_rows as _update_render_log_rows,
    _RENDER_LOG_COLUMNS as _RENDER_LOG_COLUMNS,
    _render_log_values as _render_log_values,
    _render_log_html as _render_log_html,
    _read_render_log_entries as _read_render_log_entries,
    _write_render_log as _write_render_log,
    _RenderLogTable as _RenderLogTable,
)
from preview_services.executables import (
    _blender_executable as _blender_executable,
)
from preview_services.blender import (
    _render_wireframe_eevee as _render_wireframe_eevee,
)
from preview_services.obj import (
    _OBJ_YAW as _OBJ_YAW,
    _OBJ_PITCH as _OBJ_PITCH,
    _decode_obj_image as _decode_obj_image,
    _rasterize_obj_numpy as _rasterize_obj_numpy,
    _rasterize_obj_qpainter as _rasterize_obj_qpainter,
)
from preview_services.alembic import (
    _is_legacy_alembic as _is_legacy_alembic,
    _decode_abc_image as _decode_abc_image,
)
from preview_services.maya import (
    _mayapy_executable as _mayapy_executable,
    _render_ma_wireframe as _render_ma_wireframe,
)
from preview_services.houdini import (
    _hython_executable as _hython_executable,
    _HIP_EXPORT_SCRIPT as _HIP_EXPORT_SCRIPT,
    _render_hip_wireframe as _render_hip_wireframe,
)
from preview_services.video import (
    VIDEO_PREVIEW_SEEK_FRACTION as VIDEO_PREVIEW_SEEK_FRACTION,
    VIDEO_PREVIEW_TIMEOUT_MS as VIDEO_PREVIEW_TIMEOUT_MS,
    _decode_video_frame as _decode_video_frame,
)
from preview_services.runtime import (
    _read_preview_pixmap as _read_preview_pixmap,
    file_image_pixmap as file_image_pixmap,
    _cached_file_image_pixmap as _cached_file_image_pixmap,
    _PreviewDecodeSignals as _PreviewDecodeSignals,
    _set_render_execution_state as _set_render_execution_state,
    _rename_render_directory as _rename_render_directory,
    _render_turntable_frame as _render_turntable_frame,
    _PreviewDecodeTask as _PreviewDecodeTask,
    _PREVIEW_DECODE_POOL as _PREVIEW_DECODE_POOL,
    _IDLE_SCAN_POOL as _IDLE_SCAN_POOL,
    _IMAGE_DECODE_POOL as _IMAGE_DECODE_POOL,
    _PreviewDecodeManager as _PreviewDecodeManager,
    _PREVIEW_DECODE_MANAGER as _PREVIEW_DECODE_MANAGER,
)
from preview_services.scheduler import (
    _IdleFileScanSignals as _IdleFileScanSignals,
    _IdleFileScanTask as _IdleFileScanTask,
    _IdlePreviewScheduler as _IdlePreviewScheduler,
)

from preview_services import images as _images, memory as _memory, profiles as _profiles
from preview_services import cache as _cache, runtime as _runtime, optional as _optional

_DYNAMIC_OWNERS = {
    'LUT_DEFAULT_IMAGE': _images,
    'LUT_IMAGE_CURVES': _images,
    'LUT_TEST_IMAGES': _images,
    'OpenEXR': _optional,
    '_AUTOMATIC_RENDER_PROFILE': _profiles,
    '_AUTOMATIC_RENDER_PROFILES': _profiles,
    '_PREVIEW_CACHE_HAS_PNG': _memory,
    '_PROTECTED_PREVIEW_PATHS': _cache,
    '_RENDER_PROFILES': _profiles,
    '_image_decode_order': _runtime,
    'np': _optional,
    'rawpy': _optional,
}

__all__ = [
    '_NUMPY_AVAILABLE', '_RAWPY_AVAILABLE', '_OPENEXR_AVAILABLE', '_set_hidden', '_FILE_ATTRIBUTE_NORMAL',
    '_clear_hidden', '_MTIME_CACHE', '_MTIME_TTL', '_MEMORY_ONLY', '_MTIME_PENDING',
    '_MTIME_PENDING_LOCK', '_MtimeSignals', 'MTIME_SIGNALS', 'memory_only', 'requests_held',
    '_refresh_mtimes', '_queue_mtime', '_REMOTE_DRIVES', 'is_remote_path', 'cached_mtime',
    'forget_mtime', '_smooth_scale_down', '_contain_square', '_cover_crop_rect', 'SOFTWARE_ICONS',
    '_software_icon_cache', 'software_icon_key', 'custom_software_icon_path', 'UI_ICON_FOLDER_DEFAULT', 'UI_ICON_FILE_DEFAULT',
    'UI_ICON_PIN_INACTIVE', 'UI_ICON_PIN_ACTIVE', 'UI_ICON_SETTINGS_GEAR', 'UI_ICON_SETTINGS_STYLE', 'UI_ICON_APP_LOGO',
    'UI_ICON_NAVBAR_MIN', 'UI_ICON_NAVBAR_MAX', 'UI_ICON_NAVBAR_CLOSE', 'UI_ICON_NAVBAR_BROWSE', 'UI_ICON_NAVBAR_PRESETS',
    'UI_ICON_NAVBAR_CRUMB_SEPARATOR', 'UI_ICON_NAVBAR_VIEWER', 'UI_ICON_NAVBAR_TEXT_EDITOR', 'UI_ICON_NAVBAR_BOARD', 'UI_ICON_COLLAPSE_TOGGLE',
    'UI_ICON_SHORTCUT', 'UI_ICON_VIEWER_HIDE', 'UI_ICON_VIEWER_SHOW', 'UI_ICON_VIEWER_GALLERY', 'UI_ICON_VIEWER_SINGLE',
    'UI_ICON_VIEWER_FILTER', 'UI_ICON_VIEWER_STAR_ON', 'UI_ICON_VIEWER_STAR_OFF', 'UI_ICON_VIEWER_FLAG_KEEP', 'UI_ICON_VIEWER_FLAG_DELETE',
    'UI_ICON_VIEWER_PLUS', 'UI_ICON_VIEWER_RECURSIVE', 'VIEWER_BUTTON_ICONS', 'VIEWER_ICON_KEYS', '_UI_ICON_CACHE',
    'custom_ui_icon_pixmap', '_FALLBACK_SOFTWARE_BADGE_PALETTE', '_CACHE_MAX_ENTRIES', '_bounded_cache_set', '_file_image_cache',
    '_file_image_high_cache', '_file_image_column_cache', '_FILE_IMAGE_COLUMN_PREVIEW_MAX_DIM', '_FILE_IMAGE_COLUMN_CACHE_MAX_ENTRIES', '_FILE_IMAGE_COLUMN_LOOKUP_MISSES',
    '_cache_file_preview', '_PREVIEW_STALE_LOOKUP_MISSES', '_ABR_MAX_BRUSHES', '_ABR_SAMPLE_MAX_DIM', '_abr_unpackbits',
    '_abr_read_sample', '_abr_brushes', '_abr_desc_order', '_decode_abr_image', '_oda_environment',
    '_oda_file_converter', '_DWG_THUMBNAIL_SENTINEL', '_decode_dwg_thumbnail', '_decode_dwg_image', '_render_dxf_file',
    '_render_dwg_with_oda', '_FONT_RENDER_LOCK', '_decode_font_image', 'pdf_page_count', '_render_pdf_page',
    'ai_has_pdf_content', '_decode_ai_xmp_thumbnail', '_decode_ai_image', '_decode_psd_thumbnail', '_oiiotool_executable',
    '_decode_tx_image', '_decode_exr_image', '_LUT_CURVE_NAMES', 'lut_image_kind', 'lut_curve_choices',
    '_lut_default_curve', '_GAMUT_PRIMARIES', '_D65', '_CURVE_GAMUT', '_rgb_to_xyz',
    '_log_encode', '_raw_linear_in_gamut', '_encode_8bit_as_log', 'lut_test_image_for', '_decode_raw_log_image',
    '_lut_test_image_signature', 'set_lut_test_images', '_parse_cube_lut', '_apply_cube_lut', '_lut_test_image',
    '_decode_cube_image', '_decode_raw_image', '_decode_embedded_jpeg', '_decode_hdr_image', '_decode_2d_image',
    'OBJ_PREVIEW_MAX_TRIANGLES', 'OBJ_PREVIEW_RENDER_EDGES', 'OBJ_PREVIEW_DIM', 'RENDER_PARAMETERS_PATH', '_render_value',
    '_load_render_profiles', 'RENDER_PROFILES_SNAPSHOT', '_write_profiles_snapshot', '_initial_render_profiles', '_reload_render_profiles',
    '_begin_automatic_render_batch', '_render_profile', '_apply_render_background', 'FILE_IMAGE_CACHE_MAX_DIM', 'FILE_IMAGE_DISK_CACHE_DIR',
    'AUTO_RENDER_ENABLED', 'IMAGE_DISK_CACHE_ENABLED', '_IMAGE_CACHE_SUFFIXES', '_PREVIEW_CACHE_VERSION', '_TURNTABLE_CACHE_VERSION',
    'TURNTABLE_FRAME_COUNT', 'TURNTABLE_EXTENSIONS', '_cache_slug', '_cache_label', '_cache_digest_of',
    '_cache_glob', '_CacheDirIndex', '_CACHE_INDEX', '_turntable_cache_path', '_turntable_metadata_path',
    '_turntable_work_path', '_turntable_frames', '_PREVIEW_PROTECTION_FILE', '_protected_preview_paths', '_is_preview_protected',
    '_set_preview_protected', '_file_image_cache_signature', '_file_image_cache_path', '_preview_cache_metadata_path', 'delete_preview_cache',
    '_keep_cache_digests', 'prune_unused_previews', 'sweep_preview_cache', '_SWEEP_YIELD_S', 'SWEEP_INTERVAL_S',
    'sweep_preview_cache_if_due', 'migrate_cache_names', '_record_preview_cache', '_preview_cache_metadata_matches', '_find_stale_preview_cache',
    '_prune_stale_disk_cache', '_render_log_line', '_render_log_path', '_RENDER_LOG_LOCK', '_update_render_log_rows',
    '_RENDER_LOG_COLUMNS', '_render_log_values', '_render_log_html', '_read_render_log_entries', '_write_render_log',
    '_RenderLogTable', '_blender_executable', '_render_wireframe_eevee', '_OBJ_YAW', '_OBJ_PITCH',
    '_decode_obj_image', '_rasterize_obj_numpy', '_rasterize_obj_qpainter', '_is_legacy_alembic', '_decode_abc_image',
    '_mayapy_executable', '_render_ma_wireframe', '_hython_executable', '_HIP_EXPORT_SCRIPT', '_render_hip_wireframe',
    'VIDEO_PREVIEW_SEEK_FRACTION', 'VIDEO_PREVIEW_TIMEOUT_MS', '_decode_video_frame', '_read_preview_pixmap', 'file_image_pixmap',
    '_cached_file_image_pixmap', '_PreviewDecodeSignals', '_set_render_execution_state', '_rename_render_directory', '_render_turntable_frame',
    '_PreviewDecodeTask', '_PREVIEW_DECODE_POOL', '_IDLE_SCAN_POOL', '_IMAGE_DECODE_POOL', '_PreviewDecodeManager',
    '_PREVIEW_DECODE_MANAGER', '_IdleFileScanSignals', '_IdleFileScanTask', '_IdlePreviewScheduler', 'TWO_D_IMAGE_EXTENSIONS',
]

def __getattr__(name):
    module = _DYNAMIC_OWNERS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(module, name)


def __dir__():
    return sorted(set(globals()) | _DYNAMIC_OWNERS.keys())
