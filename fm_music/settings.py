"""Réglages de FM Music (fenêtre « Réglages : FM Music ») : lignes `CATALOG["Music : …"]` et arbre `MUSIC_TREE`.
Données seulement. Défauts : `settings_defaults.py` (moteur partagé : périphérique, export, plugins et
fréquence des projets neufs sont dans l'onglet de FM Audio)."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec

from .settings_defaults import MUSIC_DEFAULTS as D

MUSIC_TAB = "Module Music"

CATALOG["Music : Général"] = [
    Spec("music_open_double_click", "Double-clic sur un projet musical ou un MIDI : FM Music", "bool", D["music_open_double_click"]),
    Spec("music_snap", "Aimanter à la grille", "bool", D["music_snap"]),
]
CATALOG["Music : Nouveaux morceaux"] = [
    Spec("music_new_tempo", "Tempo", "slider", D["music_new_tempo"], {"min": 40, "max": 240, "unit": "bpm"}),
    Spec("music_new_signature", "Signature", "choice", D["music_new_signature"],
         {"choices": (("4/4", "4/4"), ("3/4", "3/4"), ("2/4", "2/4"), ("6/8", "6/8"), ("5/4", "5/4"), ("7/8", "7/8")), "width": 90}),
    Spec("music_new_demo", "Commencer avec une batterie et une basse (sinon une piste synthé vide)", "bool", D["music_new_demo"]),
]
CATALOG["Music : Édition"] = [
    Spec("music_grid", "Grille du piano roll", "choice", D["music_grid"],
         {"choices": ((960, "Noire (1/4)"), (480, "Croche (1/8)"), (320, "Croche de triolet (1/8 T)"),
                      (240, "Double croche (1/16)"), (120, "Triple croche (1/32)")), "width": 200}),
    Spec("music_swing_default", "Swing proposé", "slider", D["music_swing_default"], {"min": 0, "max": 100, "unit": "%"}),
]

MUSIC_TREE = (
    Node("Général", "Music : Général"),
    Node("Nouveaux morceaux", "Music : Nouveaux morceaux"),
    Node("Édition", "Music : Édition"),
)
