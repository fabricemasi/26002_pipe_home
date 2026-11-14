"""Réglages de FM Audio et du moteur audio partagé (fenêtre « Réglages : FM Audio ») : lignes
`CATALOG["Audio : …"]` et arbre `AUDIO_TREE`. Données seulement : la fenêtre générique les construit.
Défauts : `settings_defaults.py`. FM Music a son onglet : `fm_music/settings.py`. Le périphérique se choisit
aussi depuis l'éditeur (bouton « Audio… », liste réelle des périphériques WASAPI et des pilotes ASIO) : ici,
sa valeur enregistrée."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

from .settings_defaults import AUDIO_DEFAULTS as D

AUDIO_TAB = "Module Audio"

CATALOG["Audio : Général"] = [
    Spec("audio_enabled", "FM Audio et FM Music actifs (menus, double-clic, Board)", "bool", D["audio_enabled"]),
    Spec("audio_open_double_click", "Double-clic sur un son : FM Audio", "bool", D["audio_open_double_click"]),
    Spec("audio_mixer_visible", "Mixer visible à l'ouverture", "bool", D["audio_mixer_visible"]),
    Spec("audio_library_root", "Dossier de la bibliothèque commune (vide = local)", "text", D["audio_library_root"]),
]
CATALOG["Audio : Nouveaux projets"] = [
    Spec("audio_new_sample_rate", "Fréquence d'un projet neuf (FM Audio et FM Music)", "choice", D["audio_new_sample_rate"],
         {"choices": ((44100, "44 100 Hz"), (48000, "48 000 Hz"), (88200, "88 200 Hz"), (96000, "96 000 Hz")), "width": 140}),
]
CATALOG["Audio : Périphérique"] = [
    Spec("audio_output_device", "Sortie (identifiant WASAPI, « asio:<pilote> », « default » = sortie Windows)", "text",
         D["audio_output_device"]),
    Spec("audio_input_device", "Entrée (vide = aucune capture ; ASIO : entrées du même pilote)", "text", D["audio_input_device"]),
    Spec("audio_buffer", "Taille du buffer (0 = période du pilote)", "slider", D["audio_buffer"], {"min": 0, "max": 2048, "unit": "éch."}),
    Spec("audio_exclusive", "Mode exclusif WASAPI (latence plus faible, périphérique réservé)", "bool", D["audio_exclusive"]),
]
CATALOG["Audio : Enregistrement et export"] = [
    Spec("audio_precount_bars", "Précompte avant l'enregistrement", "slider", D["audio_precount_bars"], {"min": 0, "max": 4, "unit": "mes."}),
    Spec("audio_metronome_level", "Volume du métronome", "slider", D["audio_metronome_level"], {"min": 0, "max": 1}),
    Spec("audio_tuner_reference", "Accordeur : fréquence du la", "slider", D["audio_tuner_reference"], {"min": 415, "max": 466, "unit": "Hz"}),
    Spec("audio_export_format", "Format d'export", "choice", D["audio_export_format"],
         {"choices": (("pcm24", "WAV 24 bits (dither)"), ("pcm16", "WAV 16 bits (dither)"), ("f32", "WAV 32 bits flottant")), "width": 200}),
]
CATALOG["Audio : Plugins VST3"] = [
    Spec("audio_plugin_dirs", "Dossiers de plugins en plus des dossiers standard (séparés par ;)", "text", D["audio_plugin_dirs"]),
    Spec("audio_plugin_scan_timeout", "Délai du scan d'un module avant quarantaine", "slider", D["audio_plugin_scan_timeout"],
         {"min": 5, "max": 120, "unit": "s"}),
]
# Outils du cadre « FM Audio » / « FM Music » de la barre de navigation (main_window/audio_module._SOUND_TOOLS) : icône
# du catalogue (preview_column.NAV_LIBRARY_ICONS), remplaçable ici comme les autres icônes de l'appli.
SOUND_FRAME_ICONS = (("sound_play", "Icône lecture"), ("sound_record", "Icône enregistrer"),
                     ("sound_loop", "Icône boucle"), ("sound_metronome", "Icône métronome"),
                     ("sound_mixer", "Icône mixer"))
CATALOG["Audio : Icônes du cadre"] = [Spec(f"ui_icon:{key}", label, "ui_icon", None, {"ui_key": key})
                                      for key, label in SOUND_FRAME_ICONS]

AUDIO_TREE = (
    Node("Général", "Audio : Général"),
    Node("Nouveaux projets", "Audio : Nouveaux projets"),
    Node("Périphérique", "Audio : Périphérique"),
    Node("Enregistrement et export", "Audio : Enregistrement et export"),
    Node("Plugins VST3", "Audio : Plugins VST3"),
    Node("Icônes du cadre", "Audio : Icônes du cadre"),
)
