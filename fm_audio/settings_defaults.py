"""Réglages par défaut de FM Audio / FM Music et du moteur partagé (sans Qt).
Fusionnés dans settings_store.DEFAULT_SETTINGS ; clés en `audio_*`."""

AUDIO_DEFAULTS = {
    "audio_enabled": True,               # désactive FM Audio / FM Music (menus, double-clic, Board)
    "audio_open_double_click": True,     # double-clic sur un son d'une colonne : FM Audio
    "audio_output_device": "default",    # identifiant WASAPI, « asio:<pilote> » ou « default »
    "audio_input_device": "",            # vide = pas d'entrée (aucune capture sans choix explicite)
    "audio_buffer": 0,                   # 0 = période par défaut du pilote
    "audio_exclusive": False,
    "audio_metronome_level": 0.5,
    "audio_precount_bars": 1,
    "audio_export_format": "pcm24",      # f32 | pcm24 | pcm16
    "audio_mixer_visible": True,
    "audio_tuner_reference": 440.0,      # accordeur : fréquence du la (Hz)
    "audio_library_root": "",            # bibliothèque commune (vide = %LOCALAPPDATA%\PIPE_FMZ\bibliotheque_audio)
    "audio_new_sample_rate": 48000,      # fréquence d'un projet neuf (FM Audio, FM Music, création depuis une colonne)
    "audio_plugin_dirs": "",             # dossiers VST3 en plus des dossiers standard (séparés par ;)
    "audio_plugin_scan_timeout": 20,     # délai du scan isolé d'un module VST3 (s) avant quarantaine
}
# FM Music : fm_music/settings_defaults.py (MUSIC_DEFAULTS).
