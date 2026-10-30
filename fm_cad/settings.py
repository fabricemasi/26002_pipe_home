"""Réglages du CAD (onglet « CAD » de la fenêtre « Réglages : Board ») : lignes `CATALOG["CAD : …"]`, arbre
`CAD_TREE` et `CAD_GROUPS` (mêmes lignes dans la fenêtre « accrochages et suivi » de la barre CAD, `cad_ui`).
Données seulement (aucun widget). Défauts : `settings_defaults.py`. Carte : docs/agents/fm_cad.md."""
from __future__ import annotations

from settings_catalog import _BORD, CATALOG, Node, Spec

CAD_TAB = "Module CAD"


def _cad_groups() -> dict:
    """Onglet « Module CAD » : lignes par section (cles `board_cad_*`). Memes lignes dans la fenetre « accrochages et
    suivi » ouverte depuis la barre d'outils CAD (« Changement de style a la volee », `CAD_GROUPS`)."""
    from fm_cad import cad_model
    from fm_cad.cad_snap import ENGLISH, LABELS, MODES
    osnap = ("board_cad_osnap", True)
    snap = [Spec("board_cad_osnap", "Accrochages aux objets — OSNAP (F3)", "bool", True)]
    for mode in MODES:
        snap.append(Spec(f"board_cad_osnap_{mode}", f"Accrochage : {LABELS[mode]} ({ENGLISH[mode]})", "bool",
                         mode in ("end", "mid", "int", "ext", "cen"), {"active_when": osnap}))
    snap += [
        Spec("board_cad_aperture", "Distance de détection (pixels d'écran)", "slider", 10, {"min": 2, "max": 40}),
        Spec("board_cad_markers", "Marqueurs d'accrochage", "bool", True),
        Spec("board_cad_marker_size", "Taille des marqueurs (pixels)", "slider", 12,
             {"min": 6, "max": 30, "active_when": ("board_cad_markers", True)}),
        Spec("board_cad_marker_thickness", "Épaisseur des marqueurs (pixels)", "slider", 2,
             {"min": 1, "max": 3, "active_when": ("board_cad_markers", True)}),
        Spec("board_cad_marker_color", "Couleur des marqueurs", "color_app", "#ff7a00",
             {"title": "Marqueurs d'accrochage", "active_when": ("board_cad_markers", True)}),
        Spec("board_cad_tooltips", "Infobulles (type d'accrochage, polaire, commandes)", "bool", True),
    ]
    tracking = [
        Spec("board_cad_ortho", "Mode orthogonal — ORTHO (F8)", "bool", False),
        Spec("board_cad_polar", "Suivi polaire (F10)", "bool", False),
        Spec("board_cad_polar_increment", "Incrément polaire", "choice", "45",
             {"choices": (("15", "15°"), ("30", "30°"), ("45", "45°"), ("90", "90°"), ("custom", "Personnalisé")),
              "width": 140}),
        Spec("board_cad_polar_custom", "Incrément personnalisé (degrés)", "slider", 45,
             {"min": 1, "max": 180, "unit": "°", "active_when": ("board_cad_polar_increment", "custom")}),
        Spec("board_cad_otrack", "Suivi d'accrochage — OTRACK (F11)", "bool", False),
        Spec("board_cad_track_polar", "Suivi d'accrochage selon les angles polaires (sinon orthogonal)", "bool",
             True, {"active_when": ("board_cad_otrack", True)}),
        Spec("board_cad_track_color", "Couleur des lignes de suivi", "color_app", "#18a058",
             {"title": "Lignes de suivi"}),
        Spec("board_cad_dyn", "Saisie dynamique — DYN (F12)", "bool", True),
    ]
    # Une seule grille (celle du board : Reglages > Module MRO > Grille ; F7 = l'afficher) : RESOL s'y accroche.
    grid = [
        Spec("board_cad_grid_snap", "Accrochage à la grille du board (niveau affiché) — RESOL (F9)", "bool", False),
    ]
    units = [
        Spec("board_cad_unit", "Unité de mesure (saisie, affichage, types de ligne)", "choice", "mm",
             {"choices": tuple((k, cad_model.UNITS[k][0]) for k in cad_model.UNIT_CHOICES), "width": 200}),
    ]
    linetypes = [Spec("board_cad_linetypes", "Types de ligne", "cad_linetypes", [])]
    # Tout ce qui concerne le reticule (chaque ligne est aussi remplacable par dessin : reglages du dessin).
    crosshair = [
        Spec("board_cad_crosshair", "Réticule en croix", "bool", True),
        Spec("board_cad_crosshair_size", "Longueur des bras (pixels)", "slider", 40,
             {"min": 8, "max": 400, "active_when": [("board_cad_crosshair", True), ("board_cad_crosshair_full", False)]}),
        Spec("board_cad_crosshair_full", "Bras jusqu'aux bords de la vue", "bool", False,
             {"active_when": ("board_cad_crosshair", True)}),
        Spec("board_cad_crosshair_auto_color", "Couleur automatique (selon le fond du canvas)", "bool", True),
        Spec("board_cad_crosshair_color", "Couleur du réticule", "color_app", "#1a1a1a",
             {"title": "Réticule", "active_when": ("board_cad_crosshair_auto_color", False)}),
        Spec("board_cad_pickbox", "Carré central : demi-côté (pixels d'écran, = boîte de sélection)", "slider", 5,
             {"min": 1, "max": 20}),
        Spec("board_cad_magnet", "Aimant : le réticule saute sur le point accroché (objets)", "bool", True),
        Spec("board_cad_magnet_radius", "Aimant : rayon d'action sur les poignées (pixels d'écran)", "slider", 10,
             {"min": 2, "max": 50, "active_when": ("board_cad_magnet", True)}),
        Spec("board_cad_magnet_tooltip", "Aimant : infobulle du point (même sans accrochage objet)", "bool", True,
             {"active_when": ("board_cad_magnet", True)}),
        Spec("board_cad_crosshair_memory", "Indicateur « propriétés en mémoire » (pipette) sur le réticule", "bool", True),
    ]
    selection = [
        Spec("board_cad_pickadd", "Clic = ajouter à la sélection (Maj = retirer), comme PICKADD", "bool", False),
        Spec("board_cad_grip_size", "Taille des poignées (pixels)", "slider", 8, {"min": 4, "max": 20}),
        Spec("board_cad_grip_color", "Couleur des poignées", "color_app", "#2f6bff", {"title": "Poignées"}),
        Spec("board_cad_grip_border_color", "Couleur du contour des poignées", "color_app", "#ffffff",
             {"title": "Contour des poignées"}),
    ]

    # Cadres de selection (demande de l'utilisateur) : fenetre (gauche -> droite) et capture (droite -> gauche).
    def frame(prefix: str, bg: str, title: str) -> list:
        return [
            Spec(f"{prefix}_bg", "Couleur de fond", "color_app", bg, {"title": f"Fond — {title}"}),
            Spec(f"{prefix}_border_enabled", "Bordure", "sides_thick", True, _BORD(f"{prefix}_border"),
                 extra_keys=(f"{prefix}_border", f"{prefix}_border_thickness")),
            Spec(f"{prefix}_radius", "Border radius", "corners", 0, {"max": 40}),
            Spec(f"{prefix}_line", "Type de ligne", "line_pattern", "solid" if "window" in prefix else "dash",
                 {"scale_key": f"{prefix}_line_scale"}, extra_keys=(f"{prefix}_line_scale",)),
        ]
    window_frame = frame("board_cad_window", "#283c6eff", "fenêtre")
    crossing_frame = frame("board_cad_crossing", "#2850c878", "capture")
    trim = [
        Spec("board_cad_trim_mode", "Mode par défaut (Rapide : tous les objets coupent, comme AutoCAD)", "choice",
             "quick", {"choices": (("quick", "Rapide"), ("standard", "Standard")), "width": 170}),
        Spec("board_cad_trim_edge", "Arêtes de coupe prolongées (EDGEMODE)", "bool", False),
    ]
    display = [
        Spec("board_cad_gpu", "Rendu GPU (OpenGL) des entités CAD — essai, fluidité du zoom et du déplacement", "bool",
             False),
        Spec("board_cad_lineweights", "Afficher les épaisseurs de ligne (éteint : simples lignes, comme AutoCAD)", "bool", True),
        Spec("board_cad_aa_samples", "Anticrénelage du rendu GPU (échantillons par pixel)", "choice", "8",
             {"choices": (("1", "Couverture exacte seule"), ("2", "2x"), ("4", "4x"), ("8", "8x"), ("16", "16x"),
                          ("32", "32x"), ("64", "64x")), "width": 200}),
        Spec("board_cad_aa_filter", "Adoucissement du suréchantillonnage (rayon du filtre)", "slider", 75,
             {"min": 50, "max": 200, "unit": "%"}),
        Spec("board_cad_antialiasing", "Anticrénelage des lignes", "bool", True),
        Spec("board_cad_linear_blend", "Anticrénelage corrigé du gamma (bords et arrondis lisses)", "bool", True,
             {"active_when": ("board_cad_antialiasing", True)}),
        Spec("board_cad_crisp_lines", "Traits fins nets (horizontaux et verticaux calés sur les pixels)", "bool", True),
        Spec("board_cad_dense_px", "Motif de ligne trop serré : trait continu sous (pixels)", "slider", 4,
             {"min": 1, "max": 20}),
        Spec("board_cad_ghost_color", "Couleur des fantômes (déplacer, copier)", "color_app", "#5f6b78",
             {"title": "Fantômes"}),
        Spec("board_cad_bar_color", "Fond des barres du CAD (outils et commande)", "color_app", "#0a0a0a",
             {"title": "Barres du CAD"}),
        Spec("board_cad_precision", "Décimales affichées", "slider", 4, {"min": 0, "max": 8, "unit": ""}),
    ]
    dims = [
        Spec("board_cad_dim_text", "Hauteur du texte", "slider", 250,
             {"min": 10, "max": 100000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_dim_arrow", "Taille des flèches", "slider", 250,
             {"min": 0, "max": 100000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_dim_gap", "Écart des lignes d'attache à leur origine", "slider", 100,
             {"min": 0, "max": 100000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_dim_over", "Dépassement des lignes d'attache", "slider", 125,
             {"min": 0, "max": 100000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_dim_scale", "Échelle des cotations (texte, flèches, écarts)", "slider", 100,
             {"min": 1, "max": 100000, "unit": "%", "box": 84}),
        Spec("board_cad_dim_arrow_kind", "Forme des flèches", "choice", "triangle",
             {"choices": (("triangle", "Triangle"), ("open", "Ouverte"), ("tick", "Trait oblique")), "width": 170}),
        Spec("board_cad_dim_decimals", "Décimales (zéros de fin retirés)", "slider", 2, {"min": 0, "max": 8, "unit": ""}),
    ]
    hatches = [
        Spec("board_cad_hatch_pattern", "Motif par défaut", "choice", "lines",
             {"choices": (("solid", "Plein"), ("lines", "Lignes"), ("cross", "Croisé"), ("brick", "Briques")),
              "width": 170}),
        Spec("board_cad_hatch_angle", "Angle du motif", "slider", 45, {"min": 0, "max": 179, "unit": "°"}),
        Spec("board_cad_hatch_spacing", "Espacement des traits", "slider", 300,
             {"min": 1, "max": 1000000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_hatch_alpha", "Opacité du remplissage plein", "slider", 35, {"min": 0, "max": 100, "unit": "%"}),
    ]
    justify = tuple((code, f"{code} — {label}") for code, label in (
        ("L", "Gauche (ligne de base)"), ("C", "Centre (ligne de base)"), ("R", "Droite (ligne de base)"),
        ("TL", "Haut gauche"), ("TC", "Haut centre"), ("TR", "Haut droite"), ("ML", "Milieu gauche"),
        ("MC", "Milieu centre"), ("MR", "Milieu droite"), ("BL", "Bas gauche"), ("BC", "Bas centre"),
        ("BR", "Bas droite")))

    def font_choices():
        from PySide6.QtGui import QFontDatabase
        return tuple((family, family) for family in QFontDatabase.families())
    texts = [
        Spec("board_cad_text_height", "Hauteur du texte (capitales)", "slider", 250,
             {"min": 1, "max": 100000, "scale": 100, "unit": "", "box": 84}),
        Spec("board_cad_text_font", "Police", "choice", "Arial", {"choices": font_choices, "width": 220}),
        Spec("board_cad_text_justify", "Justification du texte (TEXTE)", "choice", "L",
             {"choices": justify, "width": 220}),
        Spec("board_cad_mtext_justify", "Justification du texte multiligne (MTEXTE)", "choice", "TL",
             {"choices": justify, "width": 220}),
        Spec("board_cad_text_spacing", "Interligne (100 % = 5/3 de la hauteur, comme AutoCAD)", "slider", 100,
             {"min": 25, "max": 400, "unit": "%"}),
    ]
    shortcuts = [
        Spec("board_cad_pgp_path", "Fichier d'alias (.pgp d'AutoCAD)", "cad_pgp_path", ""),
    ]
    try:
        from fm_board.model import CAD_ICON_ROWS
    except Exception:                                   # noqa: BLE001 - paquet absent : pas de lignes
        CAD_ICON_ROWS = []
    icons = [Spec(f"ui_icon:ui_board_{kind}", label, "ui_icon", None, {"ui_key": f"ui_board_{kind}"})
             for kind, label in CAD_ICON_ROWS]
    return {"CAD : Unités": units, "CAD : Types de ligne": linetypes, "CAD : Accrochages": snap,
            "CAD : Suivi et saisie": tracking, "CAD : Grille": grid, "CAD : Réticule": crosshair,
            "CAD : Sélection et poignées": selection, "CAD : Fenêtre de sélection": window_frame,
            "CAD : Capture": crossing_frame, "CAD : Ajuster": trim, "CAD : Affichage": display, "CAD : Cotations": dims, "CAD : Hachures": hatches,
            "CAD : Textes": texts,
            "CAD : Raccourcis clavier": shortcuts,
            "CAD : Icônes": icons}


CAD_GROUPS = ("CAD : Accrochages", "CAD : Suivi et saisie", "CAD : Grille", "CAD : Réticule",
              "CAD : Sélection et poignées", "CAD : Affichage")
CATALOG.update(_cad_groups())


# Onglet « Module CAD » (voir CATALOG["CAD : …"]).
CAD_TREE = (
    Node("Unités", "CAD : Unités"),
    Node("Types de ligne", "CAD : Types de ligne"),
    Node("Accrochages", "CAD : Accrochages"),
    Node("Suivi et saisie", "CAD : Suivi et saisie"),
    Node("Grille", "CAD : Grille"),
    Node("Réticule", "CAD : Réticule"),
    Node("Sélection", children=(
        Node("Clic et poignées", "CAD : Sélection et poignées"),
        Node("Fenêtre (de gauche à droite)", "CAD : Fenêtre de sélection"),
        Node("Capture (de droite à gauche)", "CAD : Capture"),
    )),
    Node("Ajuster", "CAD : Ajuster"),
    Node("Affichage", "CAD : Affichage"),
    Node("Cotations", "CAD : Cotations"),
    Node("Hachures", "CAD : Hachures"),
    Node("Textes", "CAD : Textes"),
    Node("Raccourcis clavier", "CAD : Raccourcis clavier"),
    Node("Icônes", "CAD : Icônes"),
)
