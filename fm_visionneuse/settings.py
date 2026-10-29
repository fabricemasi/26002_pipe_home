"""Réglages de la visionneuse : lignes de la fenêtre « Réglages : Visionneuse » (groupes `CATALOG["Visionneuse…"]`),
arbre `VIEWER_TREE`, sous-sections de la pellicule (`VIEWER_FILM_GROUPS`, aussi au clic droit sur la pellicule) et
lignes de la fenêtre des filtres (`FILTER_ROW_SPECS`). Données seulement (aucun widget) : la fenêtre générique
`settings_window_v2.SettingsWindowV2(module="viewer")` les construit. Défauts : `settings_defaults.py`.
Carte : docs/agents/fm_visionneuse.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec, _gabarit_extra, _shadow_spec


CATALOG["Visionneuse"] = [
    # params["shortcut"] : raccourci clavier de la ligne, dans une colonne « Raccourci » du tableau.
    Spec("viewer_filmstrip_enabled", "Diapositives sous l'image en focus", "bool", True,
         {"shortcut": Spec("viewer_filmstrip_shortcut", "Raccourci", "shortcut", "D")}),
    Spec("viewer_slide_enabled", "Effet slide entre les images", "bool", True),
    Spec("viewer_gallery_ripple_enabled", "Animation des diapositives (image en focus -> planche)", "bool", True),
    Spec("viewer_scroll_animated", "Scrolling animé", "bool", True, {"toggle_style": "toggle1"}),
    Spec("viewer_info_enabled", "Paramètres de l'image", "bool", False,
         {"shortcut": Spec("viewer_info_shortcut", "Raccourci", "shortcut", "I")}),
    # Meme reglage que le bouton « Recursif » de la visionneuse (etat temps reel, `_LIVE_STATE_KEYS`).
    Spec("viewer_recursive", "Récursif (photos des sous-dossiers)", "bool", False),
]


def _viewer_film_specs(part: str, font_label: str, image: bool = False) -> list:
    """Diapositives (focus.FocusFilmstrip) : tableau (une cellule par vignette) et ses deux sous-cellules
    (image, texte dessous). Memes lignes et gabarits que le reste de la v2 ; cles `viewer_film_<part>_*`."""
    pre = f"viewer_film_{part}"

    def border(key, label):
        return Spec(f"{key}_border_enabled", label, "sides_thick", False,
                    {"colors_key": f"{key}_border", "thickness_key": f"{key}_border_thickness",
                     "width": 90, "box": 54},
                    extra_keys=(f"{key}_border", f"{key}_border_thickness"))

    rows = [border(pre, "Bordures"), Spec(f"{pre}_border_radius", "Border radius", "corners", 0, {"max": 30})]
    if part == "table":
        rows.append(_shadow_spec(f"{pre}_shadow"))
    if image:
        rows += [Spec("viewer_film_bg_padding", "Padding du fond", "padding", {}),
                 Spec("viewer_film_image_padding", "Padding de l'image", "padding", {}),
                 # Icones des attributs (couleurs, drapeaux, note, « + ») : leur propre calque, a part de l'image.
                 Spec("viewer_film_attr_padding", "Padding des icônes d'attribut", "padding", {}),
                 border("viewer_film_image", "Bordures de l'image"),
                 Spec("viewer_film_image_border_radius", "Border radius de l'image", "corners", 0, {"max": 30}),
                 _shadow_spec("viewer_film_image_shadow", "Ombres de l'image")]
    rows += [
        Spec(f"{pre}_font_family", font_label, "font_gabarit", "",
             {"prefix": pre, "size": (6, 40), "size_default": 11, "color_default": "#d6d9dc",
              "color_title": "Couleur du texte"}, extra_keys=_gabarit_extra(pre)),
        Spec(f"{pre}_bg", "Couleur de fond", "color", "#00000000", {"title": "Couleur de fond"}),
    ]
    if part == "table":
        # Planche : filets entre ses cellules (meme gabarit que Reglages > Tableaux), puis case en cours /
        # survolee (sur ses deux sous-cellules, sans bordure).
        rows += [Spec(f"{pre}_inner_{axis}_enabled", f"Bordure intérieure {axis.upper()}", "inner_line", False,
                      {"axis": axis, "prefix": f"{pre}_inner"},
                      extra_keys=(f"{pre}_inner_{axis}_color", f"{pre}_inner_{axis}_thickness"))
                 for axis in ("h", "v")]
        rows += [Spec(f"{pre}_focus_color", "Couleur focus", "color", "#465f9bd0", {"title": "Couleur focus"}),
                 Spec(f"{pre}_hover_color", "Couleur survol", "color", "#165f9bd0", {"title": "Couleur survol"})]
    return rows


# Sous-sections de Visionneuse (et choix du clic droit sur la pellicule) : (titre, groupe du CATALOG).
VIEWER_FILM_GROUPS = (("Tableau", "Visionneuse : Tableau"), ("Cellules", "Visionneuse : Cellule image"))
CATALOG["Visionneuse : Tableau"] = _viewer_film_specs("table", "Police (rang n / N)")
CATALOG["Visionneuse : Cellule image"] = _viewer_film_specs("image_cell", "Police (type de fichier)", image=True)
CATALOG["Visionneuse : Cellule texte"] = _viewer_film_specs("text_cell", "Police (nom du fichier)")
# Cadre « Visionneuse » de la barre de navigation : les boutons de la visionneuse y sont regroupes.
CATALOG["Visionneuse : Regroupement"] = [
    Spec("viewer_group_bg_color", "Couleur de fond", "color_app", "#00000000", {"title": "Fond du regroupement"}),
    Spec("viewer_group_label_font_family", "Police du libellé", "font_gabarit", "",
         {"prefix": "viewer_group_label", "size": (6, 40), "size_default": 9, "bold_default": True,
          "color_default": "#7d858b", "color_title": "Couleur du libellé"},
         extra_keys=_gabarit_extra("viewer_group_label")),
    Spec("viewer_group_border_enabled", "Bordures", "sides_thick", True,
         {"colors_key": "viewer_group_border", "thickness_key": "viewer_group_border_thickness",
          "width": 90, "box": 54}, extra_keys=("viewer_group_border", "viewer_group_border_thickness")),
    Spec("viewer_group_corner_radius", "Border radius", "corners", 4, {"max": 30}),
    Spec("viewer_group_padding", "Padding", "padding", {}),
    Spec("viewer_group_margin", "Margin", "padding", {}),
]
# Image en FOCUS (au centre de la visionneuse, focus.FocusOverlay) : son cadre.
CATALOG["Visionneuse : Focus"] = [
    Spec("viewer_focus_image_border_enabled", "Bordures de l'image", "sides_thick", False,
         {"colors_key": "viewer_focus_image_border", "thickness_key": "viewer_focus_image_border_thickness",
          "width": 90, "box": 54},
         extra_keys=("viewer_focus_image_border", "viewer_focus_image_border_thickness")),
    Spec("viewer_focus_image_border_radius", "Border radius de l'image", "corners", 0, {"max": 100}),
    _shadow_spec("viewer_focus_image_shadow", "Ombres de l'image"),
]

# Filtres (file_attributes) : les 5 couleurs attribuables aux fichiers dans la visionneuse.
CATALOG["Visionneuse : Filtres"] = [
    spec for n in range(1, 6) for spec in (
        Spec(f"viewer_filter_color_{n}_name", f"Nom de la couleur {n}", "text", ""),
        Spec(f"viewer_filter_color_{n}", f"Couleur {n}", "color", "#808080", {"title": f"Couleur {n}"}))
] + [Spec("viewer_filter_active_color", "Bouton filtre actif", "color", "#c62828", {"title": "Bouton filtre actif"}),
       # Planche : calque de la couleur attribuee a un fichier (une ligne : opacite | bordure | epaisseur).
       Spec("viewer_filter_mark_opacity", "Opacité des couleurs attribuées", "color_mark", 35,
            {"border_key": "viewer_filter_mark_border", "thickness_key": "viewer_filter_mark_border_thickness"},
            extra_keys=("viewer_filter_mark_border", "viewer_filter_mark_border_thickness"))]

# Fenetre des filtres : style des lignes ou un filtre est applique (aussi au clic droit dans la fenetre).
FILTER_ROW_SPECS = [
    Spec("viewer_filter_row_bg_enabled", "Couleur de fond", "bg_fill", True,
         {"color_key": "viewer_filter_row_bg_color", "color_default": "#403d7fd9", "title": "Fond des filtres actifs"},
         extra_keys=("viewer_filter_row_bg_color",)),
    Spec("viewer_filter_row_border_enabled", "Bordures", "sides_thick", False,
         {"colors_key": "viewer_filter_row_border", "thickness_key": "viewer_filter_row_border_thickness",
          "width": 90, "box": 54},
         extra_keys=("viewer_filter_row_border", "viewer_filter_row_border_thickness")),
    Spec("viewer_filter_row_radius", "Border radius", "corners", 0, {"max": 20}),
    Spec("viewer_filter_row_margin", "Margin", "padding", {}),
]
CATALOG["Visionneuse : Filtres"] = CATALOG["Visionneuse : Filtres"] + FILTER_ROW_SPECS


# Visionneuse > Icones : boutons de la rangee du haut et attributs des diapositives (meme mecanisme et memes
# champs que ICONES > General ; sans icone choisie, le glyphe peint par defaut reste).
VIEWER_ICON_ROWS = (("viewer_hide", "Masquer les colonnes"), ("viewer_show", "Réafficher les colonnes"),
                    ("viewer_gallery", "Planche"), ("viewer_single", "Image en cours"),
                    ("viewer_filter", "Filtres"), ("viewer_recursive", "Récursif"), ("viewer_star_on", "Note : étoile allumée"),
                    ("viewer_star_off", "Note : étoile vide"), ("viewer_flag_keep", "Drapeau : marquée"),
                    ("viewer_flag_delete", "Drapeau : rejetée"), ("viewer_plus", "Mots clés : « + »"))
CATALOG["Visionneuse : Icones"] = [
    Spec(f"ui_icon:{suffix}", label, "ui_icon", None, {"ui_key": suffix}) for suffix, label in VIEWER_ICON_ROWS
]


# Fenetre « Visionneuse » (avant : section Visionneuse de l'onglet General, choix de l'utilisateur 2026-10-29).
VIEWER_TAB = "Visionneuse"
VIEWER_TREE = (
    Node("Affichage", "Visionneuse"),
    *(Node(t, g) for t, g in VIEWER_FILM_GROUPS),
    Node("Focus", "Visionneuse : Focus"),
    Node("Regroupement", "Visionneuse : Regroupement"),
    Node("Filtres", "Visionneuse : Filtres"),
    Node("Icônes", "Visionneuse : Icones"),
)
