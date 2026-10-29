"""Défauts des réglages du module vidéo (source unique) : `settings_store` les fusionne dans DEFAULT_SETTINGS.
Aucun import (lu au chargement des réglages, avant Qt). Lignes de la fenêtre de réglages : `fm_video/settings.py`."""
from typing import Any

VIDEO_DEFAULTS: dict[str, Any] = {
    # Ouverture
    "video_open_videos": True, "video_open_sequences": True, "video_detect_sequences": True,
    # Affichage
    **{f"auto_{task}_{key}": value for task in ("settings", "moodboard", "video")
       for key, value in (("enabled", task == "settings"), ("when", "app"), ("delay", 60))},
    "video_moodboard_proxy_width": 1200,
    "video_bg_color": "#141414", "video_moodboard_bg_color": "#202020", "video_default_zoom": "smart", "video_wheel_zoom": True, "video_zoom_step": 25,
    "video_analysis_colors": 16, "video_analysis_exclude_black": False, "video_analysis_exclude_white": False,
    "video_match_lut_size": 33, "video_match_intensity": 100, "video_match_method": 0,
    "video_help_enabled": True, "video_help_delay": 350, "video_help_width": 500,
    "video_mood_info_enabled": False, "video_mood_info_timestamp": True, "video_mood_info_interval": True,
    "video_mood_info_font_size": 11, "video_mood_info_color": "#ffffff", "video_mood_info_bg": "#000000",
    "video_mood_info_opacity": 75, "video_mood_info_radius": 2, "video_mood_info_padding": 4,
    "video_mood_info_format": "clock", "video_mood_info_position": "top_right",
    "video_mood_info_margin_x": 4, "video_mood_info_margin_y": 4,
    "video_interpolation": "auto", "video_mipmaps": True, "video_pan": "bounded", "video_fit_margin": 0,
    "video_checker": True, "video_checker_size": 12, "video_checker_a": "#3a3a3a", "video_checker_b": "#262626",
    "video_backend": "auto", "video_fullscreen_autohide": True, "video_fullscreen_info": True,
    "video_controls_bg": "#16181a", "video_controls_color": "#c4cacf", "video_controls_height": 34,
    # Cadre de l'image (autour du rectangle VISIBLE de la vidéo ; affichage seulement, jamais exporté). L'ombre :
    # SHADOW_PREFIXES (« video_frame_shadow ») + décalages / extension ci-dessous.
    "video_frame_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "video_frame_border_enabled_linked": True,
    "video_frame_border": {"top": "#5f666b", "right": "#5f666b", "bottom": "#5f666b", "left": "#5f666b"},
    "video_frame_border_thickness": 1,
    "video_frame_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "video_frame_radius_linked": True,
    "video_frame_shadow_offset_x": 0, "video_frame_shadow_offset_y": 6, "video_frame_shadow_spread": 0,
    # Informations en surimpression (touche I)
    "video_info_enabled": False, "video_info_opacity": 60, "video_info_bg": "#000000",
    "video_info_font_family": "", "video_info_font_bold": False, "video_info_font_size": 12,
    "video_info_font_color": "#e8e8e8", "video_info_label_color": "#9aa0a6", "video_info_title_color": "#ffffff",
    "video_info_corner": "top_right", "video_info_margin_x": 16, "video_info_margin_y": 16,
    "video_info_line_spacing": 3, "video_info_padding": 10, "video_info_radius": 6, "video_info_width": 0,
    "video_info_compact": False, "video_info_titles": True, "video_info_temporary": False, "video_info_timeout": 3,
    "video_info_media": True, "video_info_image": True, "video_info_playback": True, "video_info_display": True,
    "video_info_pixel": True,
    # Lecture
    "video_sequence_fps": "24", "video_autoplay": True, "video_loop": True, "video_volume": 80,
    # Moteur des vidéos : « vlc » (LibVLC : décodage matériel, son, réseau) ou « pyav » ; caches de VLC (ms).
    "video_engine": "vlc", "video_cache_local_ms": 1000, "video_cache_network_ms": 1500,
    "video_end_behavior": "stop", "video_priority": "smooth", "video_missing": "black",
    "video_prefetch_ahead": 24, "video_prefetch_behind": 8, "video_reset_position": True,
    "video_key_in": "Shift+I", "video_key_out": "Shift+O", "video_key_clear": "Shift+X",
    # Timeline
    "video_timeline_height": 54, "video_timeline_tick": 8, "video_timeline_density": 80,
    "video_time_display": "frames", "video_timeline_zoom_step": 25, "video_timeline_zoom_cursor": True,
    "video_timeline_playhead": "#ff5a36", "video_timeline_selection": "#3a6ea5", "video_timeline_in": "#4caf50",
    "video_timeline_out": "#e05252", "video_timeline_bg": "#17191b", "video_timeline_ruler": "#24272b",
    "video_timeline_text": "#a8adb3", "video_timeline_cache": True, "video_timeline_thumbs": True,
    "video_timeline_thumb_height": 40,
    # Couleur
    "video_ocio_config": "", "video_display": "sRGB - Display", "video_view_video": "Un-tone-mapped",
    "video_view_image": "Un-tone-mapped", "video_input_video": "sRGB Encoded Rec.709 (sRGB)",
    "video_input_exr": "Linear Rec.709 (sRGB)", "video_input_float": "Linear Rec.709 (sRGB)",
    "video_input_int": "sRGB Encoded Rec.709 (sRGB)", "video_alpha_mode": "auto", "video_channel": "rgb",
    "video_grade_on_change": "keep", "video_clipping": False,
    # LUT
    "video_lut_dir": "", "video_lut_default": "", "video_lut_auto": False, "video_lut_mix": 100,
    "video_lut_position": "display",
    # Performances
    "video_cache_mb": 3072, "video_workers": 4, "video_diagnostics": False,
    # Export
    "video_export_format": "mp4", "video_export_codec": "h264", "video_export_crf": 18,
    "video_export_preset": "medium", "video_export_dir": "", "video_export_color": "display",
    "video_export_lut": True, "video_export_fps_mode": "resample", "video_export_interp": "minterpolate",
    "video_export_audio": True, "video_export_depth": "half", "video_export_numbering": "source",
    "video_export_overwrite": False, "video_rife_path": "",
    # État temps réel : corrections en cours, presets de corrections, derniers réglages d'export.
    "video_grade": {}, "video_grade_presets": {}, "video_export_last": {}, "video_last_zoom": {},
    "video_scopes": False,
}
