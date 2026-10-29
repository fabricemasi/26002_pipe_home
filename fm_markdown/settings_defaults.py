"""Défauts des réglages du module Markdown (source unique) : `settings_store` les fusionne dans DEFAULT_SETTINGS.
Aucun import de l'appli (lu au chargement des réglages, avant Qt). Lignes de la fenêtre : `fm_markdown/settings.py`."""
from typing import Any

# -- Module Markdown / code (paquet fm_markdown/, fenêtre « Réglages : Markdown ») ---------------------------------
# SOURCE UNIQUE de l'apparence des notes (lecture ET edition, inspecteur compris) : fm_markdown/style.py traduit ces
# cles en variables CSS. Valeurs d'origine = celles du CSS de l'utilisateur (snippet « fabrice.css » de son coffre,
# octobre 2026) ; couleurs au format de l'appli (#aarrggbb quand elles ont une opacite).

def _md_font(prefix: str, family: str, size: int, color: str, bold: bool = False, italic: bool = False) -> dict:
    """Cles d'une ligne « police » (gabarit des reglages : police | gras | italique | hauteur | couleur)."""
    return {f"{prefix}_font_family": family, f"{prefix}_font_bold": bold, f"{prefix}_font_italic": italic,
            f"{prefix}_font_size": size, f"{prefix}_font_smoothing_enabled": False,
            f"{prefix}_font_smoothing": "current", f"{prefix}_font_color": color}


def _md_sides(key: str, sides: tuple, color: str, thickness: int) -> dict:
    """Cles d'une ligne « Bordures » : cotes allumes, couleur par cote, epaisseur, « lier les 4 »."""
    every = ("top", "right", "bottom", "left")
    return {key: {s: s in sides for s in every}, key.replace("_enabled", ""): {s: color for s in every},
            key.replace("_enabled", "_thickness"): thickness, f"{key}_linked": False}


def _md_box(key: str, left: int, top: int, right: int, bottom: int) -> dict:
    return {key: {"left": left, "top": top, "right": right, "bottom": bottom}, f"{key}_linked": False}


MD_DEFAULT_CSS = r"C:\Users\fabrice\Documents\Obsidian\Fabrice\Fabrice\.obsidian\snippets\fabrice.css"

MARKDOWN_DEFAULTS: dict[str, Any] = {
    # Ouverture : extensions ouvertes au double-clic (les autres fichiers texte / code s'ouvrent par le bouton
    # « Éditeur » de la barre), double-clic sur une note .md (« module » ou l'application Obsidian), mode a
    # l'ouverture d'une note (« last », « edit », « reading »), syntaxe masquee hors du curseur en edition.
    "md_open_extensions": [".md"],
    "md_open_md": "module",
    "md_default_mode": "last",
    "md_live_preview": True,
    "md_preload": True,
    # Feuille CSS chargee par-dessus l'habillage (Reglages > Markdown > CSS) : par defaut l'extrait CSS du coffre
    # Obsidian de l'utilisateur (demande de l'utilisateur ; chemin propre a sa machine — absent ailleurs = style integre).
    "md_css_path": MD_DEFAULT_CSS,
    # Page
    "md_bg_color": "#1b1c1d",
    "md_bg_secondary": "#282a2c",
    "md_accent_color": "#5ca6f5",
    "md_selection_color": "#405ca6f5",
    "md_content_width": 0,
    "md_module_padding": 0,
    **_md_box("md_page_padding", 40, 28, 40, 28),
    **_md_box("md_page_margin", 0, 0, 0, 0),
    **_md_sides("md_page_border_enabled", (), "#ff5e6366", 1),
    "md_page_radius": {"top_left": 0, "top_right": 0, "bottom_right": 0, "bottom_left": 0},
    "md_page_radius_linked": False,
    "md_scroll_width": 10,
    "md_scroll_radius": 5,
    "md_scroll_thumb_color": "#1fffffff",
    "md_scroll_thumb_hover_color": "#33ffffff",
    "md_scroll_track_color": "#00000000",
    "md_scroll_offset": 0,
    "md_scroll_padding": 0,
    "md_zoom": 100,
    # Texte normal
    **_md_font("md_text", "Inter", 16, "#bfffffff"),
    "md_text_weight": 400,
    "md_line_height": 150,
    "md_letter_spacing": 0,
    "md_paragraph_spacing": 16,
    # Titre de la note (nom du fichier, au-dessus du texte)
    "md_title_enabled": True,
    **_md_font("md_title", "Cantarell", 32, "#ffffcf67"),
    "md_title_weight": 500,
    "md_title_spacing": 20,
    # Titres H1 a H6 (police, graisse, interligne, espace avant / apres)
    **{key: value for n, (color, weight) in enumerate((("#ff4bafff", 700), ("#ff4bafff", 300), ("#ffcba54e", 700),
                                                       ("#ffcba54e", 600), ("#ffd16f2e", 700), ("#ffd16f2e", 300)),
                                                      start=1)
       for key, value in {**_md_font(f"md_h{n}", "Cantarell", 18, color), f"md_h{n}_weight": weight,
                          f"md_h{n}_line_height": 130, f"md_h{n}_space_before": 24,
                          f"md_h{n}_space_after": 8}.items()},
    # Mise en forme du texte
    "md_bold_color": "#ffffcf67",
    "md_bold_weight": 700,
    "md_italic_color": "#bfffffff",
    "md_strike_color": "#80ffffff",
    "md_strike_line_color": "#99ff6464",
    "md_strike_bg": "#1a808080",
    "md_highlight_bg": "#66ff0000",
    "md_highlight_color": "#ffffffff",
    "md_markup_color": "#ff6a7075",
    "md_tag_color": "#ff5ca6f5",
    "md_tag_bg": "#265ca6f5",
    # Liens
    **_md_font("md_link", "JetBrains Mono", 16, "#ffb44747"),
    "md_link_letter_spacing": -5,
    "md_link_underline": False,
    "md_link_hover_underline": True,
    "md_link_unresolved_opacity": 60,
    # Listes
    "md_list_indent": 28,
    "md_list_spacing": 2,
    "md_bullet_1_char": "●", "md_bullet_1_font_size": 12, "md_bullet_1_font_color": "#ff5e6366", "md_bullet_1_vertical_offset": 0,
    "md_bullet_2_char": "○", "md_bullet_2_font_size": 10, "md_bullet_2_font_color": "#ff5e6366", "md_bullet_2_vertical_offset": 0,
    "md_bullet_3_char": "◆", "md_bullet_3_font_size": 8, "md_bullet_3_font_color": "#ff5e6366", "md_bullet_3_vertical_offset": 0,
    "md_number_color": "#ff8a9196",
    "md_checkbox_color": "#ff5ca6f5",
    "md_checkbox_size": 15,
    "md_task_done_strike": True,
    "md_task_done_color": "#80ffffff",
    # Citations
    **_md_font("md_quote", "", 16, "#ff00ff00", italic=True),
    "md_quote_bg": "#ff242628",
    **_md_sides("md_quote_border_enabled", ("left",), "#ffb44747", 3),
    "md_quote_radius": 8, "md_quote_radius_linked": True,
    **_md_box("md_quote_padding", 16, 12, 16, 12),
    "md_quote_spacing": 16,
    # Callouts (« > [!type] titre »)
    "md_callout_bg": "#ff282a2c",
    "md_callout_border_color": "#ff666666",
    "md_callout_border_width": 3,
    "md_callout_title_color": "#ffff6f00",
    "md_callout_radius": 5, "md_callout_radius_linked": True,
    # Code en ligne
    **_md_font("md_code_inline", "JetBrains Mono", 14, "#b2a9a9a9"),
    "md_code_inline_weight": 300,
    "md_code_inline_bg": "#ff282a2c",
    "md_code_inline_radius": 4, "md_code_inline_radius_linked": True,
    **_md_box("md_code_inline_padding", 8, 2, 8, 2),
    # Blocs de code
    **_md_font("md_codeblock", "JetBrains Mono", 14, "#b2a9a9a9"),
    "md_codeblock_weight": 300,
    "md_codeblock_line_height": 150,
    "md_codeblock_bg": "#ff282a2c",
    **_md_sides("md_codeblock_border_enabled", ("left", "top", "right", "bottom"), "#ff282a2c", 1),
    "md_codeblock_radius": 8, "md_codeblock_radius_linked": True,
    **_md_box("md_codeblock_padding", 16, 12, 16, 12),
    "md_codeblock_spacing": 16,
    # Coloration syntaxique (blocs de code des notes, fichiers de code, edition comme lecture)
    "md_syntax_comment": "#ce5bbd00",
    "md_syntax_keyword": "#ffc678dd",
    "md_syntax_string": "#ff98c379",
    "md_syntax_number": "#ffd19a66",
    "md_syntax_def": "#ff61afef",
    "md_syntax_variable": "#ffe06c75",
    "md_syntax_type": "#ffe5c07b",
    "md_syntax_builtin": "#ff56b6c2",
    "md_syntax_operator": "#ff56b6c2",
    "md_syntax_property": "#ffd8b6b6",
    "md_syntax_tag": "#ffe06c75",
    "md_syntax_attribute": "#ffd19a66",
    "md_syntax_meta": "#ff8a9196",
    "md_syntax_italic_comments": False,
    # Tableaux
    **_md_font("md_table", "", 15, "#ffc6c6c6"),
    **_md_font("md_table_head", "", 15, "#ffc6c6c6", bold=True),
    "md_table_grid_color": "#ff3e4143",
    "md_table_grid_width": 1,
    "md_table_cell_bg": "#40000000",
    "md_table_alt_bg": "#40000000",
    "md_table_head_bg": "#40000000",
    "md_table_radius": 4, "md_table_radius_linked": True,
    **_md_box("md_table_cell_padding", 12, 6, 12, 6),
    "md_table_spacing": 16,
    # Separateurs
    "md_hr_color": "#39ffffff",
    "md_hr_thickness": 1,
    "md_hr_spacing": 24,
    # Images
    "md_image_max_width": 100,
    "md_image_align": "left",
    "md_image_radius": 5, "md_image_radius_linked": True,
    "md_image_spacing": 8,
    # Editeur : curseur, ligne active, syntaxe revelee, fichiers de code (police, numeros de ligne, retour a la ligne)
    "md_caret_color": "#ff5ca6f5",
    "md_caret_width": 2,
    "md_active_line_bg": "#0affffff",
    **_md_font("md_code_file", "JetBrains Mono", 14, "#ffd6d9dc"),
    "md_code_file_line_height": 150,
    "md_code_file_bg": "#ff1b1c1d",
    "md_line_numbers": True,
    "md_gutter_color": "#ff5f666b",
    "md_gutter_bg": "#00000000",
    "md_code_wrap": False,
    "md_tab_size": 4,
    # Barre d'outils (reprise du plugin Editing Toolbar)
    "md_toolbar_enabled": True,
    "md_toolbar_font_color": "#ff0000",
    "md_toolbar_background_color": "#d3f8b6",
    "md_toolbar_bg": "#b3282a2c",
    "md_toolbar_icon_color": "#ffdadada",
    "md_toolbar_icon_size": 18,
    "md_toolbar_button_size": 30,
    "md_toolbar_radius": 0, "md_toolbar_radius_linked": True,
    "md_toolbar_hover_bg": "#1affffff",
    "md_toolbar_active_bg": "#595ca6f5",
    "md_toolbar_button_radius": 4, "md_toolbar_button_radius_linked": True,
    **_md_box("md_toolbar_padding", 8, 4, 8, 4),
    **_md_box("md_toolbar_margin", 0, 0, 0, 0),
    "md_toolbar_shadow_enabled": {s: False for s in ("top", "right", "bottom", "left")},
    "md_toolbar_shadow": {s: "#8c000000" for s in ("top", "right", "bottom", "left")},
    "md_toolbar_shadow_size": 10, "md_toolbar_shadow_enabled_linked": True,
    "md_toolbar_gap": 2,
    **_md_sides("md_toolbar_border_enabled", ("bottom",), "#ff2a2e32", 1),
    "md_toolbar_centered": False,
    # Etat temps reel : dernier mode (« edit » / « reading »), taille du texte des fichiers de code (Ctrl + molette).
    "md_last_mode": "edit",
    "md_code_font_zoom": 0,
}
