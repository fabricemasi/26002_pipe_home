"""Défauts des réglages du CAD (onglet « CAD » de la fenêtre « Réglages : Board ») : source unique, fusionnés dans
DEFAULT_SETTINGS par `settings_store`. Aucun import de l'appli. Lignes de la fenêtre : `settings.py`."""
from typing import Any

CAD_DEFAULTS: dict[str, Any] = {
    # Module CAD du board (board/cad*.py, Reglages > Module CAD et sa fenetre « accrochages et suivi ») :
    # bascules (F3 OSNAP, F7 grille, F8 ORTHO, F9 accrochage a la grille, F10 polaire, F11 suivi, F12 saisie
    # dynamique), modes d'accrochage, distances en pixels d'ECRAN (meme effet a tout zoom).
    "board_cad_osnap": True,
    "board_cad_osnap_end": True, "board_cad_osnap_mid": True, "board_cad_osnap_cen": True,
    "board_cad_osnap_gcen": False, "board_cad_osnap_qua": False, "board_cad_osnap_int": True,
    "board_cad_osnap_appint": False, "board_cad_osnap_ext": True, "board_cad_osnap_per": False,
    "board_cad_osnap_tan": False, "board_cad_osnap_nea": False, "board_cad_osnap_par": False,
    "board_cad_osnap_node": False, "board_cad_osnap_ins": False,
    "board_cad_aperture": 10,
    "board_cad_markers": True, "board_cad_marker_size": 12, "board_cad_marker_color": "#ff7a00",
    "board_cad_marker_thickness": 2,
    "board_cad_tooltips": True, "board_cad_magnet": True, "board_cad_magnet_radius": 10,
    "board_cad_magnet_tooltip": True,
    "board_cad_ortho": False, "board_cad_polar": False, "board_cad_polar_increment": "45",
    "board_cad_polar_custom": 45,
    "board_cad_otrack": False, "board_cad_track_polar": True,
    "board_cad_dyn": True,
    "board_cad_grid_snap": False,
    "board_cad_unit": "mm",                       # unite de mesure (mm, cm, m, km) ; override par dessin
    "board_cad_linetypes": [],                    # types de ligne (vide = ceux d'origine, fm_cad.cad_model)
    "board_cad_pickbox": 5, "board_cad_grip_size": 8, "board_cad_pickadd": False,
    "board_cad_crosshair": True, "board_cad_crosshair_size": 40, "board_cad_crosshair_full": False,
    "board_cad_crosshair_auto_color": True, "board_cad_crosshair_color": "#1a1a1a", "board_cad_crosshair_memory": True,
    "board_cad_dim_text": 250, "board_cad_dim_arrow": 250, "board_cad_dim_gap": 100, "board_cad_dim_over": 125,
    "board_cad_dim_scale": 100, "board_cad_dim_arrow_kind": "triangle", "board_cad_dim_decimals": 2,   # cotations (centiemes d'unite de mesure)
    "board_cad_hatch_pattern": "lines", "board_cad_hatch_angle": 45, "board_cad_hatch_spacing": 300,
    "board_cad_hatch_alpha": 35,                   # hachures : motif, angle, espacement (centiemes d'unite de mesure), opacite du plein
    "board_cad_text_height": 250, "board_cad_text_font": "Arial", "board_cad_text_justify": "L",
    "board_cad_mtext_justify": "TL", "board_cad_text_spacing": 100,   # textes : hauteur (centiemes d'unite de mesure), police, justifications, interligne (%)
    "board_cad_pgp_path": "",                      # fichier .pgp d'AutoCAD : alias de commandes du CAD (fm_cad/cad_aliases.py)
    "board_cad_gpu": False,                        # rendu GPU (OpenGL) des entites CAD (fm_cad/cad_gpu.py)
    "board_cad_bar_color": "#0a0a0a",              # fond de la barre d'outils et de la barre de commande du CAD
    "board_cad_precision": 4,
    "board_cad_lineweights": True,                 # affichage des epaisseurs de ligne (faux : simples lignes d'un pixel, comme AutoCAD)
    "board_cad_aa_filter": 75,                     # largeur du filtre de reduction du suréchantillonnage (% de pixel, rayon)
    "board_cad_aa_samples": "8",                   # suréchantillonnage du rendu GPU : 1 (aucun), 2, 4, 8, 16, 32, 64
    "board_cad_antialiasing": True, "board_cad_linear_blend": True, "board_cad_crisp_lines": True, "board_cad_dense_px": 4,
    "board_cad_grip_color": "#2f6bff", "board_cad_grip_border_color": "#ffffff", "board_cad_track_color": "#18a058", "board_cad_ghost_color": "#5f6b78",
    # Cadres de selection du CAD (Reglages > Module CAD > Selection) : fenetre (gauche -> droite) et capture
    # (droite -> gauche) — fond, bordure par cote, arrondis, type de ligne (solid | dash | dot) et son echelle (%)
    **{f"board_cad_{frame}_{key}": value for frame, bg, edge, line in (
        ("window", "#283c6eff", "#285ae6", "solid"), ("crossing", "#2850c878", "#28a05a", "dash"))
       for key, value in (
           ("bg", bg), ("border_enabled", {"top": True, "right": True, "bottom": True, "left": True}),
           ("border_enabled_linked", True), ("border", {"top": edge, "right": edge, "bottom": edge, "left": edge}),
           ("border_thickness", 1), ("radius", {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0}),
           ("radius_linked", True), ("line", line), ("line_scale", 100))},
    "board_cad_trim_mode": "quick",                # AJUSTER : quick (Rapide, comme AutoCAD) | standard
    "board_cad_trim_edge": False,                  # AJUSTER : aretes de coupe prolongees (EDGEMODE = 1)
}
