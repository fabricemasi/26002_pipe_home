"""Défauts des réglages de la visionneuse (fenêtre « Réglages : Visionneuse », états temps réel de la planche) :
source unique, fusionnés dans DEFAULT_SETTINGS par `settings_store`. Aucun import de l'appli.
Lignes de la fenêtre : `settings.py`."""
from typing import Any

VIEWER_DEFAULTS: dict[str, Any] = {
    "viewer_filmstrip_enabled": True,  # visionneuse : pellicule (diapositives) sous l'image en focus
    "viewer_filmstrip_shortcut": "D",  # ... et sa touche (affiche / masque, visionneuse ouverte)
    "viewer_slide_enabled": True,      # visionneuse : l'image suivante arrive en glissant (ruban)
    "viewer_info_enabled": False,      # visionneuse : tableau des parametres de l'image, a sa droite
    "viewer_info_shortcut": "I",       # ... et sa touche
    "viewer_gallery_ripple_enabled": True,  # visionneuse -> planche : les cases apparaissent en vague
    "viewer_scroll_animated": True,    # planche : la molette fait GLISSER les lignes (sinon saut sec)
    # Diapositives de la visionneuse (focus.FocusFilmstrip) : un TABLEAU, une cellule par vignette, divisee
    # en sous-cellule image (en haut) et sous-cellule texte (le nom, dessous). Reglages > Visionneuse >
    # Tableau / Sous cellule image / Sous cellule texte, ou clic droit sur la pellicule (tableau a la volee).
    # Image en FOCUS (au centre de la visionneuse) : Reglages > Visionneuse > Focus (focus.FocusOverlay).
    "viewer_focus_image_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    # Filtres (file_attributes) : les 5 couleurs attribuables aux fichiers, nom et teinte (Reglages >
    # Visionneuse > Filtres).
    **{f"viewer_filter_color_{n}": color for n, color in
       enumerate(("#d64545", "#e0c341", "#4caf50", "#3d7fd9", "#9b59b6"), 1)},
    **{f"viewer_filter_color_{n}_name": name for n, name in
       enumerate(("Rouge", "Jaune", "Vert", "Bleu", "Violet"), 1)},
    # Bouton filtre de la planche quand un filtre est applique (demande : « le bouton devient rouge »).
    "viewer_filter_active_color": "#c62828",
    # Planche : case d'un fichier qui a une couleur attribuee = calque de cette couleur (meme place que les
    # marques focus / survol), opacite, bordure (couleur attribuee, opaque) et son epaisseur.
    "viewer_filter_mark_opacity": 35,
    "viewer_filter_mark_border": False,
    "viewer_filter_mark_border_thickness": 2,
    # Fenetre des filtres : lignes ou un filtre est applique (clic droit > « Style des filtres actives »).
    "viewer_filter_row_bg_enabled": True,
    "viewer_filter_row_bg_color": "#403d7fd9",
    "viewer_filter_row_border_enabled": {"top": False, "right": False, "bottom": False, "left": True},
    "viewer_filter_row_border": {"top": "#3d7fd9", "right": "#3d7fd9", "bottom": "#3d7fd9", "left": "#3d7fd9"},
    "viewer_filter_row_border_thickness": 2,
    "viewer_filter_row_radius": 0, "viewer_filter_row_radius_linked": True,
    "viewer_filter_row_margin": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    "viewer_filter_row_margin_linked": True,
    # Ordre des boutons de la visionneuse / planche (Ctrl + glisser ; etat temps reel) : identifiants
    # « hide », « gallery », « filter », « pur:<fichier> » (PipelineBrowser._layout_viewer_buttons).
    "viewer_button_order": [],
    # Bouton « Récursif » de la visionneuse / planche (etat temps reel) : toutes les photos du dossier,
    # sous-dossiers compris (PipelineBrowser._toggle_recursive).
    "viewer_recursive": False,
    "viewer_focus_image_border": {"top": "#5f666b", "right": "#5f666b", "bottom": "#5f666b", "left": "#5f666b"},
    "viewer_focus_image_border_thickness": 1,
    "viewer_focus_image_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "viewer_focus_image_border_radius_linked": True,
    "viewer_film_text_ratio": 0.32,    # hauteur de la sous-cellule texte / celle de l'image (Ctrl + bordure)
    "viewer_gallery_text_height": 0,   # planche : hauteur (px) de la sous-cellule texte (0 = deux lignes)
    "viewer_film_table_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "viewer_film_table_border": {"top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32"},
    "viewer_film_table_border_thickness": 1,
    "viewer_film_table_border_radius": {"top_left": 5, "top_right": 5, "bottom_right": 5, "bottom_left": 5},
    "viewer_film_table_border_radius_linked": True,
    "viewer_film_table_font_family": "",     # police du rang « n / N » (cellule en cours)
    "viewer_film_table_font_bold": True,
    "viewer_film_table_font_italic": False,
    "viewer_film_table_font_size": 11,
    "viewer_film_table_font_smoothing_enabled": False,
    "viewer_film_table_font_smoothing": "current",
    "viewer_film_table_font_color": "#8fb4d5",
    "viewer_film_table_bg": "#12ffffff",
    # Planche : case en cours / survolee, sur ses DEUX sous-cellules (pas la cellule entiere), sans bordure,
    # coins = haut de la sous-cellule image + bas de la sous-cellule texte (focus._gallery_mark).
    # Planche : filets entre les cellules (Visionneuse > Tableau > Bordure interieure H / V).
    "viewer_film_table_inner_h_enabled": False,
    "viewer_film_table_inner_h_color": "#2a2e32",
    "viewer_film_table_inner_h_thickness": 1,
    "viewer_film_table_inner_v_enabled": False,
    "viewer_film_table_inner_v_color": "#2a2e32",
    "viewer_film_table_inner_v_thickness": 1,
    "viewer_film_table_focus_color": "#465f9bd0",
    "viewer_film_table_hover_color": "#165f9bd0",
    "viewer_film_image_cell_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "viewer_film_image_cell_border": {"top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32"},
    "viewer_film_image_cell_border_thickness": 1,
    "viewer_film_image_cell_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "viewer_film_image_cell_border_radius_linked": True,
    "viewer_film_image_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "viewer_film_image_border": {"top": "#5f666b", "right": "#5f666b", "bottom": "#5f666b", "left": "#5f666b"},
    "viewer_film_image_border_thickness": 1,
    "viewer_film_image_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "viewer_film_image_border_radius_linked": True,
    "viewer_film_bg_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "viewer_film_bg_padding_linked": True,
    "viewer_film_image_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "viewer_film_image_padding_linked": True,
    "viewer_film_attr_padding": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "viewer_film_attr_padding_linked": True,
    "viewer_film_image_cell_font_family": "",   # police du type de fichier (vignette pas encore prete)
    "viewer_film_image_cell_font_bold": True,
    "viewer_film_image_cell_font_italic": False,
    "viewer_film_image_cell_font_size": 11,
    "viewer_film_image_cell_font_smoothing_enabled": False,
    "viewer_film_image_cell_font_smoothing": "current",
    "viewer_film_image_cell_font_color": "#5f666b",
    "viewer_film_image_cell_bg": "#00000000",
    "viewer_film_text_cell_border_enabled": {"top": False, "right": False, "bottom": False, "left": False},
    "viewer_film_text_cell_border": {"top": "#2a2e32", "right": "#2a2e32", "bottom": "#2a2e32", "left": "#2a2e32"},
    "viewer_film_text_cell_border_thickness": 1,
    "viewer_film_text_cell_border_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "viewer_film_text_cell_border_radius_linked": True,
    "viewer_film_text_cell_font_family": "",    # police du nom du fichier
    "viewer_film_text_cell_font_bold": False,
    "viewer_film_text_cell_font_italic": False,
    "viewer_film_text_cell_font_size": 11,
    "viewer_film_text_cell_font_smoothing_enabled": False,
    "viewer_film_text_cell_font_smoothing": "current",
    "viewer_film_text_cell_font_color": "#d6d9dc",
    "viewer_film_text_cell_bg": "#00000000",
    # Visionneuse > Regroupement : cadre « Visionneuse » de la barre de navigation (boutons de la visionneuse).
    "viewer_group_bg_color": "#00000000",
    "viewer_group_label_font_family": "", "viewer_group_label_font_size": 9, "viewer_group_label_font_bold": True,
    "viewer_group_label_font_italic": False, "viewer_group_label_font_color": "#7d858b",
    "viewer_group_label_font_smoothing_enabled": False, "viewer_group_label_font_smoothing": "current",
    "viewer_group_border_enabled": {s: True for s in ("top", "right", "bottom", "left")},
    "viewer_group_border": {s: "#303539" for s in ("top", "right", "bottom", "left")},
    "viewer_group_border_thickness": 1, "viewer_group_border_enabled_linked": True,
    "viewer_group_corner_radius": {"top_left": 4, "top_right": 4, "bottom_right": 4, "bottom_left": 4},
    "viewer_group_corner_radius_linked": True,
    "viewer_group_padding": {"left": 8, "top": 2, "right": 2, "bottom": 2}, "viewer_group_padding_linked": False,
    "viewer_group_margin": {"left": 14, "top": 0, "right": 0, "bottom": 0}, "viewer_group_margin_linked": False,
}
