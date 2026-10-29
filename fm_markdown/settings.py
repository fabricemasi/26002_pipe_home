"""Réglages du module Markdown : lignes de la fenêtre « Réglages : Markdown » (groupes `CATALOG["Markdown : …"]`) et
leur arbre (`MARKDOWN_TREE`). Données seulement (aucun widget) : la fenêtre générique
`settings_window_v2.SettingsWindowV2(module="markdown")` les construit. Défauts : `settings_defaults.py`.
Carte : docs/agents/fm_markdown.md."""
from __future__ import annotations

from settings_catalog import CATALOG, Node, Spec, _gabarit_extra, _shadow_spec
from fm_markdown.settings_defaults import MARKDOWN_DEFAULTS


# ==========================================================================
# Onglet « Markdown » (module Markdown / code, paquet mdeditor/) : TOUTE l'apparence des notes (lecture, edition,
# inspecteur) et des fichiers de code. Defauts = fm_markdown/settings_defaults.py (source unique, tires du CSS de
# l'utilisateur) ; fm_markdown/style.py traduit ces cles en variables CSS. Clic droit sur un titre de l'onglet =
# « Restaurer les valeurs d'origine » (MarkdownResetTest).
# ==========================================================================
MD_OPEN_MD = (("module", "Éditeur Markdown de l'appli"), ("obsidian", "Application Obsidian"))
MD_MODES = (("last", "Dernier mode utilisé"), ("edit", "Édition"), ("reading", "Lecture"))
MD_ALIGN = (("left", "Gauche"), ("center", "Centre"), ("right", "Droite"))
MARKDOWN_TAB = "Markdown"
_MD_ALL_FONT = ("family", "bold", "italic", "size", "color")
_MD_FONT_NO_BOLD = ("family", "italic", "size", "color")


def _md(key: str):
    return MARKDOWN_DEFAULTS[key]


def _md_font(prefix: str, label: str, only=_MD_FONT_NO_BOLD, size=(6, 72)) -> Spec:
    """Ligne « police » du gabarit (police | gras | italique | hauteur | couleur) ; sans « gras » quand la ligne a sa
    propre graisse (curseur 100-900, les poids du CSS : 300, 500…)."""
    return Spec(f"{prefix}_font_family", label, "font_gabarit", _md(f"{prefix}_font_family"),
                {"prefix": prefix, "size": size, "size_default": _md(f"{prefix}_font_size"),
                 "color_default": _md(f"{prefix}_font_color"), "color_title": label,
                 "bold_default": _md(f"{prefix}_font_bold"), "only": only},
                extra_keys=_gabarit_extra(prefix, only=tuple(n for n in only if n != "family")))


def _md_slider(key: str, label: str, low: int, high: int, unit: str = "px", **params) -> Spec:
    return Spec(key, label, "slider", _md(key), {"min": low, "max": high, "unit": unit, **params})


def _md_color(key: str, label: str) -> Spec:
    return Spec(key, label, "color_app", _md(key), {"title": label})


def _md_weight(key: str, label: str = "Graisse") -> Spec:
    return _md_slider(key, label, 100, 900, "")


def _md_sides(key: str, label: str = "Bordures") -> Spec:
    base = key.replace("_enabled", "")
    return Spec(key, label, "sides_thick", _md(key),
                {"colors_key": base, "thickness_key": f"{base}_thickness", "width": 90, "box": 54},
                extra_keys=(base, f"{base}_thickness"))


def _md_bullet(n: int) -> list[Spec]:
    prefix = f"md_bullet_{n}"
    return [Spec(f"{prefix}_char", f"Puce niveau {n}", "font_gabarit", _md(f"{prefix}_char"),
                {"prefix": prefix, "char_key": f"{prefix}_char", "char_default": _md(f"{prefix}_char"),
                 "size": (4, 40), "size_default": _md(f"{prefix}_font_size"),
                 "size_label": "Rayon", "color_default": _md(f"{prefix}_font_color"), "color_title": f"Puce niveau {n}",
                 "only": ("size", "color")},
                extra_keys=(f"{prefix}_font_size", f"{prefix}_font_color")), _md_slider(f"{prefix}_vertical_offset", f"Puce niveau {n} : hauteur", -30, 30)]


def _md_heading(n: int) -> list:
    return [_md_font(f"md_h{n}", f"Police H{n}"), _md_weight(f"md_h{n}_weight"),
            _md_slider(f"md_h{n}_line_height", "Interligne", 80, 300, "%"),
            _md_slider(f"md_h{n}_space_before", "Espace avant", 0, 120),
            _md_slider(f"md_h{n}_space_after", "Espace après", 0, 120)]


CATALOG["Markdown : Ouverture"] = [
    Spec("md_open_extensions", "Extensions ouvertes au double-clic", "extension_list", _md("md_open_extensions"),
         {"prompt": "Extension à ouvrir dans l'éditeur au double-clic (ex. .txt) :"}),
    Spec("md_open_md", "Double-clic sur une note .md", "md_open_md", _md("md_open_md")),
    Spec("md_default_mode", "Mode à l'ouverture d'une note", "md_mode", _md("md_default_mode")),
    Spec("md_live_preview", "Édition : masquer la syntaxe hors du curseur", "bool", _md("md_live_preview")),
    Spec("md_preload", "Préparer l'éditeur au démarrage (ouverture immédiate)", "bool", _md("md_preload")),
]
CATALOG["Markdown : CSS"] = [
    Spec("md_css_path", "Feuille CSS (Obsidian ou autre)", "md_css_path", _md("md_css_path")),
]
CATALOG["Markdown : Page"] = [
    _md_color("md_bg_color", "Couleur de fond"),
    _md_color("md_bg_secondary", "Couleur de fond secondaire"),
    _md_color("md_accent_color", "Couleur d'accent"),
    _md_color("md_selection_color", "Couleur de sélection"),
    _md_slider("md_module_padding", "Marge horizontale du module", 0, 1000),
    _md_slider("md_content_width", "Largeur maximale du texte (0 = toute la largeur)", 0, 2400),
    Spec("md_page_margin", "Margin", "padding", _md("md_page_margin")),
    _md_sides("md_page_border_enabled"),
    Spec("md_page_radius", "Border radius", "corners", _md("md_page_radius"), {"max": 100}),
    Spec("md_page_padding", "Padding", "padding", _md("md_page_padding")),
    _md_slider("md_scroll_width", "Barre de défilement : largeur", 4, 40),
    _md_slider("md_scroll_radius", "Barre de défilement : border radius", 0, 40),
    _md_color("md_scroll_thumb_color", "Barre de défilement : curseur"),
    _md_color("md_scroll_thumb_hover_color", "Barre de défilement : curseur au survol"),
    _md_color("md_scroll_track_color", "Barre de défilement : rail"),
    _md_slider("md_scroll_offset", "Barre de défilement : décalage intérieur", 0, 200),
    _md_slider("md_scroll_padding", "Barre de défilement : padding du curseur", 0, 20),
    _md_slider("md_zoom", "Zoom", 50, 200, "%"),
]
CATALOG["Markdown : Texte"] = [
    _md_font("md_text", "Police du texte"),
    _md_weight("md_text_weight"),
    _md_slider("md_line_height", "Interligne", 80, 300, "%"),
    _md_slider("md_letter_spacing", "Espacement des lettres (dixièmes de px)", -30, 50, ""),
]
CATALOG["Markdown : Titre de la note"] = [
    Spec("md_title_enabled", "Afficher le titre (nom du fichier)", "bool", _md("md_title_enabled")),
    _md_font("md_title", "Police du titre"),
    _md_weight("md_title_weight"),
    _md_slider("md_title_spacing", "Espace après", 0, 120),
]
for _n in range(1, 7):
    CATALOG[f"Markdown : H{_n}"] = _md_heading(_n)
CATALOG["Markdown : Mise en forme"] = [
    _md_color("md_bold_color", "Gras : couleur"),
    _md_weight("md_bold_weight", "Gras : graisse"),
    _md_color("md_italic_color", "Italique : couleur"),
    _md_color("md_strike_color", "Barré : couleur du texte"),
    _md_color("md_strike_line_color", "Barré : couleur du trait"),
    _md_color("md_strike_bg", "Barré : fond"),
    _md_color("md_highlight_bg", "Surlignage : fond"),
    _md_color("md_highlight_color", "Surlignage : texte"),
    _md_color("md_tag_color", "Tags : texte"),
    _md_color("md_tag_bg", "Tags : fond"),
    _md_color("md_markup_color", "Syntaxe révélée (#, **, [[ ]]…)"),
]
CATALOG["Markdown : Liens"] = [
    _md_font("md_link", "Police des liens", only=("family", "italic", "size", "color")),
    _md_slider("md_link_letter_spacing", "Espacement des lettres (dixièmes de px)", -30, 50, ""),
    Spec("md_link_underline", "Soulignés", "bool", _md("md_link_underline")),
    Spec("md_link_hover_underline", "Soulignés au survol", "bool", _md("md_link_hover_underline")),
    _md_slider("md_link_unresolved_opacity", "Opacité des liens introuvables", 0, 100, "%"),
]
CATALOG["Markdown : Paragraphes et listes"] = [
    _md_slider("md_paragraph_spacing", "Espace entre les paragraphes", 0, 80),
    _md_slider("md_list_indent", "Retrait des listes", 0, 80),
    _md_slider("md_list_spacing", "Espace entre les éléments", 0, 40),
    *_md_bullet(1), *_md_bullet(2), *_md_bullet(3),
    _md_color("md_number_color", "Couleur des numéros"),
    _md_color("md_checkbox_color", "Cases à cocher : couleur"),
    _md_slider("md_checkbox_size", "Cases à cocher : taille", 8, 40),
    Spec("md_task_done_strike", "Tâches faites : barrées", "bool", _md("md_task_done_strike")),
    _md_color("md_task_done_color", "Tâches faites : couleur"),
]
CATALOG["Markdown : Citations"] = [
    _md_font("md_quote", "Police des citations", only=("family", "italic", "color")),
    _md_color("md_quote_bg", "Couleur de fond"),
    _md_sides("md_quote_border_enabled"),
    Spec("md_quote_radius", "Border radius", "corners", _md("md_quote_radius"), {"max": 40}),
    Spec("md_quote_padding", "Padding", "padding", _md("md_quote_padding")),
    _md_slider("md_quote_spacing", "Espace avant / après", 0, 80),
]
CATALOG["Markdown : Callouts"] = [
    _md_color("md_callout_bg", "Couleur de fond"),
    _md_color("md_callout_border_color", "Couleur de la bordure gauche"),
    _md_slider("md_callout_border_width", "Épaisseur de la bordure gauche", 0, 16),
    _md_color("md_callout_title_color", "Couleur du titre"),
    Spec("md_callout_radius", "Border radius", "corners", _md("md_callout_radius"), {"max": 40}),
]
CATALOG["Markdown : Code en ligne"] = [
    _md_font("md_code_inline", "Police"),
    _md_weight("md_code_inline_weight"),
    _md_color("md_code_inline_bg", "Couleur de fond"),
    Spec("md_code_inline_radius", "Border radius", "corners", _md("md_code_inline_radius"), {"max": 20}),
    Spec("md_code_inline_padding", "Padding", "padding", _md("md_code_inline_padding")),
]
CATALOG["Markdown : Blocs de code"] = [
    _md_font("md_codeblock", "Police"),
    _md_weight("md_codeblock_weight"),
    _md_slider("md_codeblock_line_height", "Interligne", 80, 300, "%"),
    _md_color("md_codeblock_bg", "Couleur de fond"),
    _md_sides("md_codeblock_border_enabled"),
    Spec("md_codeblock_radius", "Border radius", "corners", _md("md_codeblock_radius"), {"max": 40}),
    Spec("md_codeblock_padding", "Padding", "padding", _md("md_codeblock_padding")),
    _md_slider("md_codeblock_spacing", "Espace avant / après", 0, 80),
]
CATALOG["Markdown : Coloration syntaxique"] = [
    _md_color(f"md_syntax_{name}", label) for name, label in (
        ("comment", "Commentaires"), ("keyword", "Mots-clés"), ("string", "Chaînes"), ("number", "Nombres"),
        ("def", "Définitions (fonctions, classes)"), ("variable", "Variables"), ("type", "Types"),
        ("builtin", "Fonctions intégrées"), ("operator", "Opérateurs"), ("property", "Propriétés"),
        ("tag", "Balises (HTML, XML)"), ("attribute", "Attributs"), ("meta", "Méta (décorateurs, directives)"))
] + [Spec("md_syntax_italic_comments", "Commentaires en italique", "bool", _md("md_syntax_italic_comments"))]
CATALOG["Markdown : Tableaux"] = [
    _md_font("md_table", "Police des cellules", only=("family", "bold", "italic", "size", "color")),
    _md_font("md_table_head", "Police de l'entête", only=_MD_ALL_FONT),
    _md_color("md_table_grid_color", "Couleur du quadrillage"),
    _md_slider("md_table_grid_width", "Épaisseur du quadrillage", 0, 8),
    _md_color("md_table_cell_bg", "Fond des cellules"),
    _md_color("md_table_alt_bg", "Fond des lignes paires"),
    _md_color("md_table_head_bg", "Fond de l'entête"),
    Spec("md_table_radius", "Border radius", "corners", _md("md_table_radius"), {"max": 30}),
    Spec("md_table_cell_padding", "Padding des cellules", "padding", _md("md_table_cell_padding")),
    _md_slider("md_table_spacing", "Espace avant / après", 0, 80),
]
CATALOG["Markdown : Séparateurs"] = [
    _md_color("md_hr_color", "Couleur"),
    _md_slider("md_hr_thickness", "Épaisseur", 0, 12),
    _md_slider("md_hr_spacing", "Espace avant / après", 0, 120),
]
CATALOG["Markdown : Images"] = [
    _md_slider("md_image_max_width", "Largeur maximale (part du texte)", 5, 100, "%"),
    Spec("md_image_align", "Alignement", "md_align", _md("md_image_align")),
    Spec("md_image_radius", "Border radius", "corners", _md("md_image_radius"), {"max": 40}),
    _md_slider("md_image_spacing", "Espace avant / après", 0, 80),
]
CATALOG["Markdown : Éditeur"] = [
    _md_color("md_caret_color", "Curseur : couleur"),
    _md_slider("md_caret_width", "Curseur : épaisseur", 1, 6),
    _md_font("md_code_file", "Fichiers de code : police"),
    _md_slider("md_code_file_line_height", "Fichiers de code : interligne", 80, 300, "%"),
    _md_color("md_code_file_bg", "Fichiers de code : fond"),
    _md_color("md_active_line_bg", "Fichiers de code : ligne en cours"),
    Spec("md_line_numbers", "Fichiers de code : numéros de ligne", "bool", _md("md_line_numbers")),
    _md_color("md_gutter_color", "Numéros de ligne : couleur"),
    _md_color("md_gutter_bg", "Numéros de ligne : fond"),
    Spec("md_code_wrap", "Fichiers de code : retour à la ligne", "bool", _md("md_code_wrap")),
    _md_slider("md_tab_size", "Largeur des tabulations", 1, 16, "esp."),
]
CATALOG["Markdown : Barre d'outils"] = [
    Spec("md_toolbar_enabled", "Afficher la barre d'outils (édition des notes)", "bool", _md("md_toolbar_enabled")),
    _md_color("md_toolbar_bg", "Couleur de fond"),
    _md_color("md_toolbar_icon_color", "Couleur des icônes"),
    _md_slider("md_toolbar_icon_size", "Taille des icônes", 8, 40),
    _md_slider("md_toolbar_button_size", "Taille des boutons", 16, 60),
    Spec("md_toolbar_radius", "Border radius de la barre", "corners", _md("md_toolbar_radius"), {"max": 30}),
    _md_color("md_toolbar_hover_bg", "Fond au survol"),
    _md_color("md_toolbar_active_bg", "Fond d'un outil actif (pinceau)"),
    Spec("md_toolbar_button_radius", "Border radius des boutons", "corners", _md("md_toolbar_button_radius"),
         {"max": 30}),
    Spec("md_toolbar_padding", "Padding", "padding", _md("md_toolbar_padding")),
    Spec("md_toolbar_margin", "Margin", "padding", _md("md_toolbar_margin")),
    _md_slider("md_toolbar_gap", "Espace entre les boutons", 0, 24),
    _shadow_spec("md_toolbar_shadow"),
    _md_sides("md_toolbar_border_enabled"),
    Spec("md_toolbar_centered", "Boutons centrés", "bool", _md("md_toolbar_centered")),
]
del _n


# Onglet « Markdown » (voir CATALOG["Markdown : …"]).
MARKDOWN_TREE = (
    Node("Ouverture", "Markdown : Ouverture"),
    Node("CSS", "Markdown : CSS"),
    Node("Page", "Markdown : Page"),
    Node("Typographie", children=(Node("Texte", "Markdown : Texte"), Node("Titre de la note", "Markdown : Titre de la note"),
                                  Node("Mise en forme", "Markdown : Mise en forme"), Node("Liens", "Markdown : Liens"))),
    Node("Titres H1-H6", children=tuple(Node(f"H{n}", f"Markdown : H{n}") for n in range(1, 7))),
    Node("Paragraphes et listes", "Markdown : Paragraphes et listes"),
    Node("Citations", "Markdown : Citations"),
    Node("Callouts", "Markdown : Callouts"),
    Node("Code", children=(Node("Code en ligne", "Markdown : Code en ligne"),
                           Node("Blocs de code", "Markdown : Blocs de code"),
                           Node("Coloration syntaxique", "Markdown : Coloration syntaxique"))),
    Node("Tableaux", "Markdown : Tableaux"),
    Node("Séparateurs", "Markdown : Séparateurs"),
    Node("Images", "Markdown : Images"),
    Node("Éditeur", "Markdown : Éditeur"),
    Node("Barre d'outils", "Markdown : Barre d'outils"),
)
