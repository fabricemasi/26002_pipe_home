"""Défauts des réglages du module Illustrator (onglet « Illustrator » de la fenêtre « Réglages : Board », clés
`board_ill_*`) : source unique, fusionnés dans DEFAULT_SETTINGS par `settings_store`. Aucun import de l'appli.
Lignes de la fenêtre : `settings.py` ; appliqués par `look.apply_settings` (appelé par `BoardPane.apply_settings`)."""
from typing import Any

ILL_DEFAULTS: dict[str, Any] = {
    # Sélection et repères (dessin temporaire, pixels d'ÉCRAN).
    "board_ill_accent": "#2f7cf6",            # couleur de sélection (contours, points, boîte, plans choisis)
    "board_ill_handle_size": 9,               # côté des poignées de la boîte englobante
    "board_ill_anchor_size": 5,               # côté des points d'ancrage (et tolérance de leur clic)
    "board_ill_smart_guides": True,           # repères commentés actifs à l'ouverture du module (Ctrl+U : la session)
    # (leur aspect : Réglages > Module MRO > Magnétisme, fm_board/snap_guides.py)
    "board_ill_snap_px": 6,                   # distance d'aimantation des repères commentés
    # Nouveaux objets.
    "board_ill_artboard_format": "A4",        # nom de `model.ARTBOARD_FORMATS` : plan de travail par défaut
    "board_ill_font": "",                     # police des nouveaux textes (« » = celle de l'appli)
    "board_ill_text_size": 12,                # corps des nouveaux textes (pt)
    "board_ill_units": "pt",                  # unité affichée (épaisseur, corps) : pt, mm, px
    # Clavier et outils.
    "board_ill_nudge": 1,                     # flèches : déplacement (unités du board)
    "board_ill_nudge_big": 10,                # flèches avec Maj
    "board_ill_pencil_fidelity": 25,          # crayon et pinceau : écart toléré à la main, en dixièmes de pixel
    "board_ill_trace_detail": 1000,           # vectorisation : grand côté de l'image tracée (px ; contours subpixel, 2026-11-13)
    # Export.
    "board_ill_pdf_dpi": 300,                 # résolution des parties tramées du PDF (effets, masques d'opacité)
}
