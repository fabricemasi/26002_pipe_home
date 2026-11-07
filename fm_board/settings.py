"""Réglages du board (onglets « Board » et « MRO » de la fenêtre « Réglages : Board ») : lignes `CATALOG["Board…"]`,
`CATALOG["MRO…"]`, arbres `BOARD_TREE` et `MRO_TREE`, sections « Icônes » de chaque module. Données seulement (aucun widget) : la fenêtre générique `settings_window_v2.SettingsWindowV2(module="board")`
les construit. Les lignes « Menus contextuels » du board sont des COPIES de celles de l'appli (`board_<clé>` +
interrupteur d'override) : faites par settings_window_v2 (elles dépendent des menus de l'appli), seuls leurs titres
(`BOARD_MENU_GROUPS`) sont ici. Défauts : `settings_defaults.py`. Onglets CAD, Design, Tableur : `fm_cad/settings.py`,
`fm_design/settings.py`, `fm_tableur/settings.py`.
Carte : docs/agents/fm_board.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec, _ctx_font, _shadow_spec

MRO_TAB = "Module MRO"
BOARD_TAB = "Module Board"             # PREMIER onglet de la fenetre « Reglages : Board » (affiche « Board »)
BOARD_MENU_GROUPS = (("Menu", "Menu contextuel : Menu"), ("Lignes", "Menu contextuel : Lignes"),
                     ("Survol", "Menu contextuel : Survol"), ("Libellés", "Menu contextuel : Libelles"),
                     ("Séparateurs", "Menu contextuel : Separateurs"))


def _board_icon_rows(rows_name: str = "ICON_ROWS"):
    """Lignes d'une section « Icônes » (une par module, demande de l'utilisateur 2026-11-05) : une ligne par bouton,
    meme champ que les autres icones. `rows_name` = liste de fm_board.model (`MRO_ICON_ROWS`... ; defaut : toutes)."""
    try:
        from fm_board import model
        rows = getattr(model, rows_name)
    except Exception:                                   # noqa: BLE001 - paquet absent : pas de lignes
        return []
    return [Spec(f"ui_icon:ui_board_{kind}", label, "ui_icon", None, {"ui_key": f"ui_board_{kind}"})
            for kind, label in rows]


# Une section « Icônes » par onglet de la fenetre « Réglages : Board » (CAD : fm_cad/settings.py, « CAD : Icônes »).
# Les noeuds de Design / Tableur / Illustrator / Photoshop sont dans leur arbre (`<paquet>/settings.py`).
ICON_GROUPS_BY_MODULE = {"Board : Icônes": "BOARD_ICON_ROWS", "MRO : Icones": "MRO_ICON_ROWS",
                         "Design : Icônes": "DESIGN_ICON_ROWS", "Tableur : Icônes": "TABLEUR_ICON_ROWS",
                         "Illustrator : Icônes": "ILL_ICON_ROWS", "Photoshop : Icônes": "PS_ICON_ROWS"}
for _group, _rows in ICON_GROUPS_BY_MODULE.items():
    CATALOG[_group] = _board_icon_rows(_rows)

def _cad_linetype_choices():
    """Types de ligne du module CAD (Réglages > Module CAD > Types de ligne : ceux installés par le board)."""
    try:
        from fm_cad import cad_model
        return tuple((key, name) for key, (name, _pattern) in cad_model.LINETYPES.items())
    except Exception:                                   # noqa: BLE001 - paquet absent : le trait continu seul
        return (("continuous", "Continu"),)


# Guides d'alignement par SORTE d'aimantation (demande de l'utilisateur 2026-11-06 : bords des documents / objets
# internes aux documents ; fm_board/snap_guides.py) : une ligne du tableau Magnétisme par sorte, sa cellule divisée
# Guide d'alignement (toggle) | Couleur du guide | Type de ligne (ceux du CAD) | Échelle du type de ligne. Grisée
# quand le maître « Guides d'alignement » est coupé (ou le magnétisme).
SNAP_GUIDE_ROWS = (("doc", "Bords des documents"), ("inner", "Objets internes aux documents"),
                   ("frame", "Cadre sur son document"))      # cadre redimensionné aimanté à son document (PDF)
_SNAP_GUIDE_LINETYPES = {"doc": "continuous", "inner": "dashed", "frame": "dashdot"}


def _snap_guide_row(kind: str, label: str) -> Spec:
    pre = f"board_snap_{kind}_"
    parts = (
        ("Guide d'alignement", Spec(pre + "guides", "Guide d'alignement", "bool", True)),
        ("Couleur du guide", Spec(pre + "color", "Couleur du guide", "color", "#ff2fd0",
                                  {"title": f"Guides : {label.lower()}"})),
        ("Type de ligne", Spec(pre + "linetype", "Type de ligne", "choice", _SNAP_GUIDE_LINETYPES[kind],
                               {"choices": _cad_linetype_choices, "width": 150})),
        ("Échelle du type de ligne", Spec(pre + "ltscale", "Échelle du type de ligne", "slider", 20,
                                          {"min": 5, "max": 100, "scale": 10, "unit": "×", "width": 120, "box": 56})),
    )
    keys = tuple(sub.key for _caption, sub in parts)
    return Spec(keys[0], label, "split_fields", None,           # cellule divisée lue / écrite comme ses champs
                {"parts": parts, "active_when": [("board_snap_enabled", True), ("board_snap_guides", True)]},
                extra_keys=keys[1:])


# Module « Board » (board/, fichiers .brd, anciens .mro) : reglages GENERAUX (le canvas d'un board se regle dans le board).
CATALOG["MRO"] = [
    Spec("board_snap_enabled", "Magnétisme (Alt tenu = sans)", "bool", True),
    Spec("board_snap_objects", "Aimanter aux autres objets (bords, centres)", "bool", True,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_grid", "Aimanter à la grille (niveau affiché)", "bool", False,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_resize", "Aimanter aussi en redimensionnant", "bool", True,
         {"active_when": ("board_snap_enabled", True)}),
    Spec("board_snap_guides", "Guides d'alignement", "bool", True, {"active_when": ("board_snap_enabled", True)}),
    *(_snap_guide_row(kind, label) for kind, label in SNAP_GUIDE_ROWS),
    Spec("board_snap_distance", "Distance d'aimantation (pixels d'écran)", "slider", 6,
         {"min": 1, "max": 30, "active_when": ("board_snap_enabled", True)}),
]


CATALOG["Board : Navigation"] = [
    Spec("board_zoom_speed", "Vitesse du zoom (par cran de molette)", "slider", 15, {"min": 1, "max": 100, "unit": "%"}),
    Spec("board_zoom_fine", "Zoom fin, Maj tenu (par cran de molette)", "slider", 3, {"min": 1, "max": 50, "unit": "%"}),
]


CATALOG["Board : Ouverture"] = [
    Spec("board_open_cad_drawings", "Double-clic sur un dessin DXF / DWG : Module MRO", "bool", True),
    Spec("board_cad_import_blocks", "Dessin DXF / DWG : garder les blocs en blocs (sinon éclatés en objets)", "bool", True),
]

# Grille UNIQUE du board et du module CAD (fm_board/scene.py, `grid_look`). Affichee ou non : bouton « Grille » de la
# barre d'outils du board (F7 en mode CAD), reglage de chaque board. Chaque ligne peut etre remplacee par dessin
# (barre CAD > Reglages du dessin, `page["cad"]["overrides"]`).
CATALOG["Board : Grille"] = [
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


# Onglet « Board » > Barre de selection (fm_board/modulebar.py, demande de l'utilisateur 2026-10-31) : les reglages
# importants de la barre de selection des modules et TOUT son habillage ; defauts = la maquette « Barre des modules ».
_SEL = "Board : Barre de sélection"
CATALOG[_SEL] = [
    Spec("board_modulebar_buttons", "Boutons afficher / griser / isoler (appui long sur l'icône d'un module)", "bool",
         True),
    Spec("board_modulebar_long_press_ms", "Appui long qui déploie ces boutons", "slider", 500,
         {"min": 150, "max": 2000, "unit": "ms", "active_when": ("board_modulebar_buttons", True)}),
    Spec("board_modulebar_reset", "Bouton « Tout afficher, sortir de l'isolation »", "bool", True),
    Spec("board_modulebar_alt_solo", "Alt + clic sur l'icône d'un module : l'isoler", "bool", True),
    Spec("board_modulebar_pill", "Pastille « Isolé » pendant une isolation", "bool", True),
    Spec("board_modulebar_fold_style", "Barre repliée", "choice", "narrow",
         {"choices": (("narrow", "Étroite, icônes seules (bouton en haut de la barre)"),
                      ("tab", "Cachée, une languette au bord la fait revenir")), "width": 330}),
    Spec("board_modules_fade_opacity", "Opacité des éléments d'un module grisé", "slider", 30,
         {"min": 5, "max": 90, "unit": "%"}),
    Spec("board_modules_fade_saturation", "Saturation des éléments d'un module grisé (0 % = gris)", "slider", 100,
         {"min": 0, "max": 100, "unit": "%"}),
]
CATALOG[f"{_SEL} : Aspect"] = [
    Spec("board_modulebar_bg_color", "Couleur de fond", "color_app", "#16181a", {"title": "Fond de la barre"}),
    Spec("board_modulebar_border_color", "Couleur du filet", "color_app", "#2a2e32",
         {"title": "Filet de la barre"}),
    Spec("board_modulebar_icon_size", "Taille des icônes des modules", "slider", 36, {"min": 20, "max": 64}),
    Spec("board_modulebar_button_size", "Taille des boutons afficher / griser / isoler", "slider", 24,
         {"min": 14, "max": 40}),
    Spec("board_modulebar_spacing", "Espace entre les lignes", "slider", 4, {"min": 0, "max": 20}),
    Spec("board_modulebar_padding", "Padding de la barre", "slider", 6, {"min": 0, "max": 24}),
    Spec("board_modulebar_row_radius", "Border radius des lignes", "slider", 8, {"min": 0, "max": 20}),
    Spec("board_modulebar_row_color", "Fond d'une ligne visible", "color_app", "#22242a",
         {"title": "Ligne visible"}),
    Spec("board_modulebar_active_alpha", "Fond du module actif (opacité de sa couleur)", "slider", 18,
         {"min": 0, "max": 100, "unit": "%"}),
    Spec("board_modulebar_hover_color", "Couleur de fond survol", "color_app", "#232729", {"title": "Survol"}),
    Spec("board_modulebar_ink_color", "Icônes des boutons (éléments affichés)", "color_app", "#d7d9de",
         {"title": "Icônes des boutons"}),
    Spec("board_modulebar_dim_color", "Module grisé, boutons éteints", "color_app", "#8b8e96",
         {"title": "Module grisé"}),
    Spec("board_modulebar_off_color", "Module masqué ou hors isolation", "color_app", "#5a5d64",
         {"title": "Module masqué"}),
    Spec("board_modulebar_fade_color", "Bouton « griser » allumé", "color_app", "#9a9ca3",
         {"title": "Bouton griser"}),
    Spec("board_modulebar_solo_color", "Isolation (bouton, cadre, pastille, point)", "color_app", "#f3c46b",
         {"title": "Isolation"}),
    Spec("board_modulebar_tool_color", "Icônes replier la barre / tout réinitialiser", "color_app", "#a4a6ad",
         {"title": "Icônes replier / réinitialiser"}),
    Spec("board_modulebar_tool_hover_alpha", "Survol replier / réinitialiser (opacité de la couleur des icônes)",
         "slider", 20, {"min": 0, "max": 100, "unit": "%"}),
]
CATALOG[f"{_SEL} : Couleurs des modules"] = [
    Spec(f"board_modulebar_color_{name}", label, "color_app", default, {"title": f"Dominante : {label}"})
    for name, label, default in (("miro", "Miro", "#f2c94c"), ("cad", "CAD", "#6fa8ff"),
                                 ("design", "Design", "#4fd1c5"), ("tableur", "Tableur", "#7bd88f"),
                                 ("illustrator", "Illustrator", "#f08bb4"),
                                 ("photoshop", "Photoshop", "#5aa9e6"), ("pdf", "PDF", "#e0604f"))
]
CATALOG[f"{_SEL} : Languette et pastille"] = [
    Spec("board_modulebar_tab_width", "Largeur de la languette", "slider", 14,
         {"min": 8, "max": 40, "active_when": ("board_modulebar_fold_style", "tab")}),
    Spec("board_modulebar_tab_height", "Hauteur de la languette", "slider", 56,
         {"min": 24, "max": 160, "active_when": ("board_modulebar_fold_style", "tab")}),
    Spec("board_modulebar_tab_color", "Fond de la languette", "color_app", "#16181a",
         {"title": "Languette", "active_when": ("board_modulebar_fold_style", "tab")}),
    Spec("board_modulebar_tab_ink", "Chevron de la languette", "color_app", "#a4a6ad",
         {"title": "Chevron", "active_when": ("board_modulebar_fold_style", "tab")}),
    Spec("board_modulebar_pill_color", "Fond de la pastille « Isolé »", "color_app", "#2a2418",
         {"title": "Pastille"}),
    Spec("board_modulebar_pill_font_size", "Taille du texte de la pastille", "slider", 13, {"min": 8, "max": 24}),
]
BOARD_TREE = (
    Node("Barre de sélection", children=(
        Node("Général", _SEL),
        Node("Aspect", f"{_SEL} : Aspect"),
        Node("Couleurs des modules", f"{_SEL} : Couleurs des modules"),
        Node("Languette et pastille", f"{_SEL} : Languette et pastille"),
    )),
    # Ouverture, Navigation, Grille : venues de l'onglet MRO (demande de l'utilisateur 2026-11-05 ; memes cles) :
    # elles valent pour tout le board, quel que soit le module.
    Node("Ouverture", "Board : Ouverture"),
    Node("Navigation", "Board : Navigation"),
    Node("Grille", "Board : Grille"),
    Node("Icônes", "Board : Icônes"),
)


# Onglet « Module MRO » (module Board, paquet board/ ; avant : section MRO de l'onglet General).
MRO_TREE = (
    Node("Magnétisme", "MRO"),
    Node("Barres d'outils", "MRO : Barres d'outils"),
    Node("Menus contextuels", children=tuple(Node(t, f"MRO : {g}") for t, g in BOARD_MENU_GROUPS)),
    Node("Icônes", "MRO : Icones"),
)
