"""Réglages du board (onglet « MRO » de la fenêtre « Réglages : Board ») : lignes `CATALOG["MRO…"]` et arbre
`MRO_TREE`. Données seulement (aucun widget) : la fenêtre générique `settings_window_v2.SettingsWindowV2(module="board")`
les construit. Les lignes « Menus contextuels » du board sont des COPIES de celles de l'appli (`board_<clé>` +
interrupteur d'override) : faites par settings_window_v2 (elles dépendent des menus de l'appli), seuls leurs titres
(`BOARD_MENU_GROUPS`) sont ici. Défauts : `settings_defaults.py`. Onglet CAD : `fm_cad/settings.py`.
Carte : docs/agents/fm_board.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec, _ctx_font, _shadow_spec

MRO_TAB = "Module MRO"
BOARD_MENU_GROUPS = (("Menu", "Menu contextuel : Menu"), ("Lignes", "Menu contextuel : Lignes"),
                     ("Survol", "Menu contextuel : Survol"), ("Libellés", "Menu contextuel : Libelles"),
                     ("Séparateurs", "Menu contextuel : Separateurs"))


def _board_icon_rows():
    """Reglages > Module MRO > Icones : une ligne par bouton du module (meme champ que les autres icones)."""
    try:
        from fm_board.model import ICON_ROWS
    except Exception:                                   # noqa: BLE001 - paquet absent : pas de lignes
        return []
    return [Spec(f"ui_icon:ui_board_{kind}", label, "ui_icon", None, {"ui_key": f"ui_board_{kind}"})
            for kind, label in ICON_ROWS]


CATALOG["MRO : Icones"] = _board_icon_rows()

# Module « Board » (board/, fichiers .mro) : reglages GENERAUX (le canvas d'un board se regle dans le board).
CATALOG["MRO"] = [
    Spec("board_snap_enabled", "Magnétisme (Alt tenu = sans)", "bool", True),
    Spec("board_snap_objects", "Aimanter aux autres objets (bords, centres)", "bool", True,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_grid", "Aimanter à la grille (niveau affiché)", "bool", False,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_resize", "Aimanter aussi en redimensionnant", "bool", True,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_guides", "Guides d'alignement", "bool", True, {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_distance", "Distance d'aimantation (pixels d'écran)", "slider", 6,
         {"min": 1, "max": 30, "active_when": ("board_snap_enabled", True)}),
]


CATALOG["MRO : Navigation"] = [
    Spec("board_zoom_speed", "Vitesse du zoom (par cran de molette)", "slider", 15, {"min": 1, "max": 100, "unit": "%"}),
    Spec("board_zoom_fine", "Zoom fin, Maj tenu (par cran de molette)", "slider", 3, {"min": 1, "max": 50, "unit": "%"}),
]


CATALOG["MRO : Ouverture"] = [
    Spec("board_open_cad_drawings", "Double-clic sur un dessin DXF / DWG : Module MRO", "bool", True),
]

# Grille UNIQUE du board et du module CAD (fm_board/scene.py, `grid_look`). Affichee ou non : bouton « Grille » de la
# barre d'outils du board (F7 en mode CAD), reglage de chaque board. Chaque ligne peut etre remplacee par dessin
# (barre CAD > Reglages du dessin, `page["cad"]["overrides"]`).
CATALOG["MRO : Grille"] = [
    Spec("board_grid_step", "Pas de base de la grille", "slider", 400,
         {"min": 1, "max": 100000, "scale": 100, "unit": "", "box": 84}),
    Spec("board_grid_unit", "Unité du pas et de l'origine", "choice", "board",
         {"choices": (("board", "Unités du board (1/96 de pouce)"), ("cad", "Unité de mesure du CAD")), "width": 230}),
    Spec("board_grid_factor", "Facteur entre deux niveaux", "slider", 4, {"min": 2, "max": 10, "unit": "×"}),
    Spec("board_grid_levels", "Niveaux visibles au plus", "slider", 12, {"min": 1, "max": 12, "unit": ""}),
    Spec("board_grid_fade_start", "Apparition d'un niveau à (pixels d'écran)", "slider", 12, {"min": 1, "max": 200}),
    Spec("board_grid_fade_full", "Niveau plein à (pixels d'écran)", "slider", 60, {"min": 2, "max": 400}),
    Spec("board_grid_origin_x", "Origine X", "slider", 0,
         {"min": -1000000, "max": 1000000, "scale": 100, "unit": "", "box": 84}),
    Spec("board_grid_origin_y", "Origine Y (vers le haut)", "slider", 0,
         {"min": -1000000, "max": 1000000, "scale": 100, "unit": "", "box": 84}),
    Spec("board_grid_style", "Style", "choice", "lines",
         {"choices": (("lines", "Lignes"), ("dots", "Points aux croisements"), ("crosses", "Croix aux croisements")),
          "width": 200}),
    Spec("board_grid_thickness", "Épaisseur (pixels)", "slider", 1, {"min": 1, "max": 6}),
    Spec("board_grid_dot_size", "Taille des points / croix (pixels)", "slider", 2,
         {"min": 1, "max": 12, "active_when": ("board_grid_style", ["dots", "crosses"])}),
    Spec("board_grid_auto_color", "Couleur automatique (noire sur canvas clair, blanche sur sombre)", "bool", True),
    Spec("board_grid_intensity", "Intensité d'un niveau plein (couleur automatique)", "slider", 66,
         {"min": 5, "max": 1000, "scale": 10, "unit": "%", "active_when": ("board_grid_auto_color", True)}),
    Spec("board_grid_color", "Couleur d'un niveau plein (son opacité compte)", "color_app", "#11000000",
         {"title": "Grille", "active_when": ("board_grid_auto_color", False)}),
    Spec("board_grid_axes", "Axes passant par l'origine", "bool", False),
    Spec("board_grid_axes_color", "Couleur des axes", "color_app", "#66ff2f2f",
         {"title": "Axes de la grille", "active_when": ("board_grid_axes", True)}),
    Spec("board_grid_axes_thickness", "Épaisseur des axes (pixels)", "slider", 1,
         {"min": 1, "max": 6, "active_when": ("board_grid_axes", True)}),
]


# Module « Board » : Reglages > Module MRO > Barres d'outils (habillage des barres flottantes du board).
CATALOG["MRO : Barres d'outils"] = [
    Spec("board_toolbar_bg_color", "Couleur de fond", "color_app", "#16181a", {"title": "Fond des barres d'outils"}),
    Spec("board_toolbar_border_enabled", "Bordures", "sides_thick", True,
         {"colors_key": "board_toolbar_border", "thickness_key": "board_toolbar_border_thickness",
          "width": 90, "box": 54}, extra_keys=("board_toolbar_border", "board_toolbar_border_thickness")),
    Spec("board_toolbar_corner_radius", "Border radius", "corners", 0, {"max": 30}),
    Spec("board_toolbar_padding", "Padding du fond", "padding", {}),
    _shadow_spec("board_toolbar_shadow"),
    _ctx_font("board_toolbar_text", "Police", 12, "#d6d9dc"),
    Spec("board_toolbar_invert", "Icônes et textes en négatif", "bool", False),
    Spec("board_toolbar_focus_width", "Largeur du focus et du survol", "slider", 26, {"min": 0, "max": 30}),
    Spec("board_toolbar_focus_color", "Couleur de fond focus", "color_app", "#6e3f6f9f"),
    Spec("board_toolbar_focus_radius", "Border radius focus", "slider", 6, {"min": 0, "max": 30}),
    Spec("board_toolbar_hover_color", "Couleur de fond survol", "color_app", "#232729"),
    Spec("board_toolbar_hover_radius", "Border radius survol", "slider", 6, {"min": 0, "max": 30}),
]


# Onglet « Module MRO » (module Board, paquet board/ ; avant : section MRO de l'onglet General).
MRO_TREE = (
    Node("Ouverture", "MRO : Ouverture"),
    Node("Navigation", "MRO : Navigation"),
    Node("Magnétisme", "MRO"),
    Node("Grille", "MRO : Grille"),
    Node("Barres d'outils", "MRO : Barres d'outils"),
    Node("Menus contextuels", children=tuple(Node(t, f"MRO : {g}") for t, g in BOARD_MENU_GROUPS)),
    Node("Icônes", "MRO : Icones"),
)
