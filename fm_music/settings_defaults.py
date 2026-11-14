"""Réglages par défaut de FM Music (sans Qt) : clés `music_*`, fusionnées dans settings_store.DEFAULT_SETTINGS.
Le moteur partagé (périphérique, export, plugins, fréquence des projets neufs) : fm_audio/settings_defaults.py."""

MUSIC_DEFAULTS = {
    "music_open_double_click": True,
    "music_snap": True,
    "music_new_tempo": 120.0,            # morceau neuf : tempo (bpm)
    "music_new_signature": "4/4",        # morceau neuf : signature
    "music_new_demo": True,              # morceau neuf : batterie + basse de départ (sinon une piste synthé vide)
    "music_grid": 240,                   # grille du piano roll en ticks (960 = noire ; 240 = double croche)
    "music_swing_default": 50,           # valeur proposée par « Swing… » (%)
}
