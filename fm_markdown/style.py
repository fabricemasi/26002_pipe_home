"""Apparence des notes : reglages `md_*` (onglet « Markdown » des reglages, defauts dans
`settings_store.MARKDOWN_DEFAULTS`) -> variables CSS.

SOURCE UNIQUE : les regles (web/base.css) ne contiennent aucune valeur d'apparence, seulement des `var(--md-…)` ;
ce module donne leurs valeurs. La meme feuille habille le mode lecture, le mode edition (CodeMirror), les fichiers
de code et l'apercu des notes dans l'inspecteur : un reglage change tout en meme temps, sans rechargement (la page
recoit le nouveau bloc de variables, `css_variables`).

Aucune dependance vers la fenetre principale ; les polices « de l'appli » (roles de Polices principales) sont
traduites en vraies familles par `FONT_RESOLVER`, pose par l'appli (repli : le libelle tel quel)."""
from __future__ import annotations

import os
from pathlib import Path

from settings_store import MARKDOWN_DEFAULTS


# (libelle, taille, graisse) -> nom de famille reel ; pose par l'appli (browser_core._resolve_font_family).
FONT_RESOLVER = None

_SIDES = ("top", "right", "bottom", "left")
_CORNERS = ("top_left", "top_right", "bottom_right", "bottom_left")
_GENERIC = {"mono": "monospace", "sans": "sans-serif"}


def _get(values: dict, key: str):
    value = values.get(key)
    return MARKDOWN_DEFAULTS.get(key) if value is None else value


def css_color(value, fallback: str = "transparent") -> str:
    """Couleur de l'appli -> CSS : « @pastille » resolue, « #aarrggbb » (Qt) -> « #rrggbbaa » (CSS)."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    value = value.strip()
    if value.startswith("@"):
        try:
            from app_style import resolve_color_ref
            value = resolve_color_ref(value, fallback)
        except Exception:                               # noqa: BLE001 - palette indisponible (tests) : repli
            return fallback
    if value.startswith("#") and len(value) == 9:
        return "#" + value[3:] + value[1:3]
    return value


def _int(value, default=0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _sides(value, default=0) -> dict:
    if isinstance(value, dict):
        return {s: _int(value.get(s, default), default) for s in _SIDES}
    return {s: _int(value, default) for s in _SIDES}


def _corners(value) -> dict:
    if isinstance(value, dict):
        return {c: max(0, _int(value.get(c, 0))) for c in _CORNERS}
    return {c: max(0, _int(value)) for c in _CORNERS}


def _box(value) -> str:
    s = _sides(value)
    return f"{s['top']}px {s['right']}px {s['bottom']}px {s['left']}px"


def _radius(value) -> str:
    c = _corners(value)
    return f"{c['top_left']}px {c['top_right']}px {c['bottom_right']}px {c['bottom_left']}px"


def _family(values: dict, prefix: str, generic: str = "sans", inherit: str | None = None) -> str:
    """Famille CSS d'une ligne « police » ; vide / « Systeme » = `inherit` (ou la famille par defaut)."""
    label = str(_get(values, f"{prefix}_font_family") or "").strip()
    if not label or label == "Systeme":
        return inherit or f"system-ui, {_GENERIC[generic]}"
    size = _int(_get(values, f"{prefix}_font_size"), 14) or 14
    family = label
    if FONT_RESOLVER is not None:
        try:
            family = FONT_RESOLVER(label, size, 400) or label
        except Exception:                               # noqa: BLE001 - role inconnu : le libelle
            family = label
    return f"\"{family.replace(chr(34), '')}\", {_GENERIC[generic]}"


def _font(values: dict, prefix: str, out: dict, name: str, generic: str = "sans", inherit: str | None = None,
          weight_key: str | None = None):
    """Variables --md-<name>-font / -size / -color / -style / -weight d'une ligne « police »."""
    out[f"--md-{name}-font"] = _family(values, prefix, generic, inherit)
    out[f"--md-{name}-size"] = f"{max(1, _int(_get(values, f'{prefix}_font_size'), 14))}px"
    out[f"--md-{name}-color"] = css_color(_get(values, f"{prefix}_font_color"), "inherit")
    out[f"--md-{name}-style"] = "italic" if _get(values, f"{prefix}_font_italic") else "normal"
    if weight_key:
        out[f"--md-{name}-weight"] = str(max(100, min(900, _int(_get(values, weight_key), 400))))
    else:
        out[f"--md-{name}-weight"] = "700" if _get(values, f"{prefix}_font_bold") else "400"


def _border(values: dict, key: str, out: dict, name: str):
    """--md-<name>-border-{top,right,bottom,left} : « <epaisseur>px solid <couleur> » ou none."""
    enabled = _get(values, key)
    colors = _get(values, key.replace("_enabled", "")) or {}
    thickness = max(0, _int(_get(values, key.replace("_enabled", "_thickness")), 1))
    for side in _SIDES:
        on = enabled.get(side, False) if isinstance(enabled, dict) else bool(enabled)
        color = colors.get(side) if isinstance(colors, dict) else colors
        out[f"--md-{name}-border-{side}"] = (f"{thickness}px solid {css_color(color, 'transparent')}"
                                             if on and thickness else "0 solid transparent")


def variables(values: dict) -> dict:
    """{nom de variable CSS: valeur} pour les reglages `values` (cles absentes = valeurs d'origine)."""
    v, out = values or {}, {}
    color = lambda key, fb="transparent": css_color(_get(v, key), fb)        # noqa: E731
    px = lambda key: f"{_int(_get(v, key))}px"                               # noqa: E731
    # Page
    out["--md-bg"] = color("md_bg_color")
    out["--md-bg-secondary"] = color("md_bg_secondary")
    out["--md-accent"] = color("md_accent_color")
    out["--md-selection"] = color("md_selection_color")
    width = _int(_get(v, "md_content_width"))
    out["--md-content-width"] = f"{width}px" if width > 0 else "none"
    out["--md-page-padding"] = _box(_get(v, "md_page_padding"))
    padding = _sides(_get(v, "md_page_padding"))
    out["--md-page-padding-right"] = f"{max(0, padding['right'])}px"
    margin = _sides(_get(v, "md_page_margin"))
    for side in _SIDES:
        out[f"--md-page-margin-{side}"] = f"{max(0, margin[side])}px"
    _border(v, "md_page_border_enabled", out, "page")
    out["--md-page-radius"] = _radius(_get(v, "md_page_radius"))
    for key in ("width", "radius", "offset"):
        out[f"--md-scroll-{key}"] = f"{max(0, _int(_get(v, f'md_scroll_{key}')))}px"
    out["--md-scroll-padding"] = f"{max(0, _int(_get(v, 'md_scroll_padding')))}px"
    for key in ("thumb_color", "thumb_hover_color", "track_color"):
        out[f"--md-scroll-{key.replace('_', '-')}"] = color(f"md_scroll_{key}")
    out["--md-zoom"] = str(max(25, _int(_get(v, "md_zoom"), 100)) / 100)
    # Texte
    _font(v, "md_text", out, "text", weight_key="md_text_weight")
    text_font = out["--md-text-font"]
    out["--md-line-height"] = str(max(80, _int(_get(v, "md_line_height"), 150)) / 100)
    out["--md-letter-spacing"] = f"{_int(_get(v, 'md_letter_spacing')) / 10}px"
    out["--md-p-spacing"] = px("md_paragraph_spacing")
    # Titre de la note et titres
    out["--md-title-display"] = "block" if _get(v, "md_title_enabled") else "none"
    _font(v, "md_title", out, "title", inherit=text_font, weight_key="md_title_weight")
    out["--md-title-spacing"] = px("md_title_spacing")
    for n in range(1, 7):
        _font(v, f"md_h{n}", out, f"h{n}", inherit=text_font, weight_key=f"md_h{n}_weight")
        out[f"--md-h{n}-before"] = px(f"md_h{n}_space_before")
        out[f"--md-h{n}-after"] = px(f"md_h{n}_space_after")
        out[f"--md-h{n}-line-height"] = str(max(80, _int(_get(v, f"md_h{n}_line_height"), 130)) / 100)
    # Mise en forme
    out["--md-bold-color"] = color("md_bold_color", "inherit")
    out["--md-bold-weight"] = str(_int(_get(v, "md_bold_weight"), 700))
    out["--md-italic-color"] = color("md_italic_color", "inherit")
    out["--md-strike-color"] = color("md_strike_color", "inherit")
    out["--md-strike-line"] = color("md_strike_line_color", "currentColor")
    out["--md-strike-bg"] = color("md_strike_bg")
    out["--md-highlight-bg"] = color("md_highlight_bg")
    out["--md-highlight-color"] = color("md_highlight_color", "inherit")
    out["--md-markup-color"] = color("md_markup_color", "inherit")
    out["--md-tag-color"] = color("md_tag_color", "inherit")
    out["--md-tag-bg"] = color("md_tag_bg")
    # Liens
    _font(v, "md_link", out, "link", inherit="inherit")
    out["--md-link-letter-spacing"] = f"{_int(_get(v, 'md_link_letter_spacing')) / 10}px"
    out["--md-link-decoration"] = "underline" if _get(v, "md_link_underline") else "none"
    out["--md-link-hover-decoration"] = "underline" if _get(v, "md_link_hover_underline") else "none"
    out["--md-link-unresolved-opacity"] = str(max(0, min(100, _int(_get(v, "md_link_unresolved_opacity"), 60))) / 100)
    # Listes
    out["--md-list-indent"] = px("md_list_indent")
    out["--md-list-spacing"] = px("md_list_spacing")
    for n in (1, 2, 3):
        char = str(_get(v, f"md_bullet_{n}_char") or "•").replace("\\", "\\\\").replace('"', '\\"')
        out[f"--md-bullet-{n}-char"] = f'"{char}"'
        out[f"--md-bullet-{n}-size"] = f"{max(1, _int(_get(v, f'md_bullet_{n}_font_size'), 12))}px"
        out[f"--md-bullet-{n}-vertical-offset"] = f"{_int(_get(v, f'md_bullet_{n}_vertical_offset'))}px"
        out[f"--md-bullet-{n}-color"] = color(f"md_bullet_{n}_font_color", "inherit")
    out["--md-number-color"] = color("md_number_color", "inherit")
    out["--md-checkbox-color"] = color("md_checkbox_color")
    out["--md-checkbox-size"] = px("md_checkbox_size")
    out["--md-task-done-decoration"] = "line-through" if _get(v, "md_task_done_strike") else "none"
    out["--md-task-done-color"] = color("md_task_done_color", "inherit")
    # Citations, callouts
    _font(v, "md_quote", out, "quote", inherit="inherit")
    out["--md-quote-bg"] = color("md_quote_bg")
    _border(v, "md_quote_border_enabled", out, "quote")
    out["--md-quote-radius"] = _radius(_get(v, "md_quote_radius"))
    out["--md-quote-padding"] = _box(_get(v, "md_quote_padding"))
    out["--md-quote-spacing"] = px("md_quote_spacing")
    out["--md-callout-bg"] = color("md_callout_bg")
    out["--md-callout-border"] = f"{_int(_get(v, 'md_callout_border_width'))}px solid {color('md_callout_border_color')}"
    out["--md-callout-title-color"] = color("md_callout_title_color", "inherit")
    out["--md-callout-radius"] = _radius(_get(v, "md_callout_radius"))
    # Code
    _font(v, "md_code_inline", out, "code-inline", "mono", weight_key="md_code_inline_weight")
    out["--md-code-inline-bg"] = color("md_code_inline_bg")
    out["--md-code-inline-radius"] = _radius(_get(v, "md_code_inline_radius"))
    out["--md-code-inline-padding"] = _box(_get(v, "md_code_inline_padding"))
    _font(v, "md_codeblock", out, "codeblock", "mono", weight_key="md_codeblock_weight")
    out["--md-codeblock-line-height"] = str(max(80, _int(_get(v, "md_codeblock_line_height"), 150)) / 100)
    out["--md-codeblock-bg"] = color("md_codeblock_bg")
    _border(v, "md_codeblock_border_enabled", out, "codeblock")
    out["--md-codeblock-radius"] = _radius(_get(v, "md_codeblock_radius"))
    out["--md-codeblock-padding"] = _box(_get(v, "md_codeblock_padding"))
    cpad = _sides(_get(v, "md_codeblock_padding"))
    out["--md-codeblock-padding-x"] = f"{cpad['left']}px"
    out["--md-codeblock-padding-right"] = f"{cpad['right']}px"
    out["--md-codeblock-padding-top"] = f"{cpad['top']}px"
    out["--md-codeblock-padding-bottom"] = f"{cpad['bottom']}px"
    out["--md-codeblock-spacing"] = px("md_codeblock_spacing")
    for name in ("comment", "keyword", "string", "number", "def", "variable", "type", "builtin", "operator",
                 "property", "tag", "attribute", "meta"):
        out[f"--md-syntax-{name}"] = color(f"md_syntax_{name}", "inherit")
    out["--md-syntax-comment-style"] = "italic" if _get(v, "md_syntax_italic_comments") else "normal"
    # Tableaux
    _font(v, "md_table", out, "table", inherit="inherit")
    _font(v, "md_table_head", out, "table-head", inherit="inherit")
    out["--md-table-grid"] = color("md_table_grid_color")
    out["--md-table-grid-width"] = px("md_table_grid_width")
    out["--md-table-cell-bg"] = color("md_table_cell_bg")
    out["--md-table-alt-bg"] = color("md_table_alt_bg")
    out["--md-table-head-bg"] = color("md_table_head_bg")
    out["--md-table-radius"] = _radius(_get(v, "md_table_radius"))
    out["--md-table-cell-padding"] = _box(_get(v, "md_table_cell_padding"))
    out["--md-table-spacing"] = px("md_table_spacing")
    # Separateurs, images
    out["--md-hr-color"] = color("md_hr_color")
    out["--md-hr-thickness"] = px("md_hr_thickness")
    out["--md-hr-spacing"] = px("md_hr_spacing")
    out["--md-image-max-width"] = f"{max(5, min(100, _int(_get(v, 'md_image_max_width'), 100)))}%"
    align = _get(v, "md_image_align")
    out["--md-image-margin-left"] = "auto" if align in ("center", "right") else "0"
    out["--md-image-margin-right"] = "auto" if align == "center" else "0"
    out["--md-image-radius"] = _radius(_get(v, "md_image_radius"))
    out["--md-image-spacing"] = px("md_image_spacing")
    # Editeur, fichiers de code
    out["--md-caret"] = color("md_caret_color", "currentColor")
    out["--md-caret-width"] = px("md_caret_width")
    out["--md-active-line"] = color("md_active_line_bg")
    _font(v, "md_code_file", out, "code-file", "mono")
    zoom = _int(_get(v, "md_code_font_zoom"))
    if zoom:
        size = max(6, _int(_get(v, "md_code_file_font_size"), 14) + zoom)
        out["--md-code-file-size"] = f"{size}px"
    out["--md-code-file-line-height"] = str(max(80, _int(_get(v, "md_code_file_line_height"), 150)) / 100)
    out["--md-code-file-bg"] = color("md_code_file_bg")
    out["--md-gutter-color"] = color("md_gutter_color", "inherit")
    out["--md-gutter-bg"] = color("md_gutter_bg")
    # Barre d'outils
    out["--md-toolbar-bg"] = color("md_toolbar_bg")
    out["--md-toolbar-icon-color"] = color("md_toolbar_icon_color", "currentColor")
    out["--md-toolbar-icon-size"] = px("md_toolbar_icon_size")
    out["--md-toolbar-button-size"] = px("md_toolbar_button_size")
    out["--md-toolbar-radius"] = _radius(_get(v, "md_toolbar_radius"))
    out["--md-toolbar-hover-bg"] = color("md_toolbar_hover_bg")
    out["--md-toolbar-active-bg"] = color("md_toolbar_active_bg")
    out["--md-toolbar-button-radius"] = _radius(_get(v, "md_toolbar_button_radius"))
    out["--md-toolbar-padding"] = _box(_get(v, "md_toolbar_padding"))
    out["--md-toolbar-margin"] = _box(_get(v, "md_toolbar_margin"))
    sides = _get(v, "md_toolbar_shadow_enabled") or {}
    colors = _get(v, "md_toolbar_shadow") or {}
    try:
        shadow_size = max(0, _int(_get(v, "md_toolbar_shadow_size")))
    except (TypeError, ValueError):
        shadow_size = 0
    shadows = []
    if shadow_size and isinstance(sides, dict):
        for side, (x, y) in {"top": (0, -1), "right": (1, 0), "bottom": (0, 1), "left": (-1, 0)}.items():
            if sides.get(side):
                value = colors.get(side, "#8c000000") if isinstance(colors, dict) else colors
                shadows.append(f"{x * shadow_size}px {y * shadow_size}px {shadow_size}px {css_color(value)}")
    out["--md-toolbar-shadow"] = ", ".join(shadows) if shadows else "none"
    out["--md-toolbar-gap"] = px("md_toolbar_gap")
    _border(v, "md_toolbar_border_enabled", out, "toolbar")
    # Marge haute nulle : le filet superieur est dessine sur le bord bas de la barre de navigation (widget Qt),
    # afin que les deux filets occupent la meme ligne au lieu d'en afficher deux l'un sous l'autre.
    if not any(_sides(_get(v, "md_toolbar_margin")).values()):
        out["--md-toolbar-border-top"] = "0 solid transparent"
    out["--md-toolbar-justify"] = "center" if _get(v, "md_toolbar_centered") else "flex-start"
    return out


def is_color_key(key: str) -> bool:
    """Reglage de couleur : le changer ne modifie aucune dimension (pas de remise en page de l'editeur)."""
    return key.startswith("md_syntax_") and key != "md_syntax_italic_comments" or key.endswith(
        ("_color", "_bg", "_bg_color", "_bg_secondary")) or key in ("md_bg_color", "md_selection_color")


def css_variables(values: dict) -> str:
    """Bloc des variables --md-* (hors couche, apres les feuilles). Chaque variable reliee a Obsidian reprend D'ABORD
    la variable d'Obsidian si une feuille chargee la definit (`var(--h1-color, <reglage>)`) : c'est la priorite de la
    feuille sur les reglages. Pose aussi sur les conteneurs ou une feuille d'Obsidian les definit (body.theme-dark,
    .markdown-preview-view…), pour que la valeur la plus proche soit reprise."""
    body = "".join(f"  {name}: {value};\n" for name, value in linked_variables(values).items())
    return VARS_SELECTOR + " {\n" + body + "}\n"


VARS_SELECTOR = ":root, body, .markdown-reading-view, .markdown-preview-view, .markdown-source-view"


def page_options(values: dict) -> dict:
    """Options de comportement lues par la page (pas d'apparence)."""
    v = values or {}
    return {
        "livePreview": bool(_get(v, "md_live_preview")),
        "toolbar": bool(_get(v, "md_toolbar_enabled")),
        "lineNumbers": bool(_get(v, "md_line_numbers")),
        "wrapCode": bool(_get(v, "md_code_wrap")),
        "tabSize": max(1, min(16, _int(_get(v, "md_tab_size"), 4))),
    }


# -- Compatibilite avec les feuilles d'Obsidian ---------------------------------------------------------------------
# Variables documentees d'Obsidian (docs.obsidian.md, Reference > CSS variables) reliees a celles du module :
# (variable du module, variables d'Obsidian LUES dans l'ordre (la 1re definie l'emporte), variables ECRITES a l'export).
# Une feuille d'Obsidian qui les definit habille donc le module ; l'export les ecrit d'apres les reglages.
_OBSIDIAN = [
    ("--md-bg", ("--background-primary",), ("--background-primary",)),
    ("--md-bg-secondary", ("--background-secondary",), ("--background-secondary",)),
    ("--md-accent", ("--interactive-accent",), ()),
    ("--md-selection", ("--text-selection",), ("--text-selection",)),
    ("--md-text-font", ("--font-text", "--font-text-theme"), ("--font-text-theme",)),
    ("--md-text-size", ("--font-text-size",), ("--font-text-size",)),
    ("--md-text-color", ("--text-normal",), ("--text-normal",)),
    ("--md-text-weight", ("--font-weight",), ("--font-weight",)),
    ("--md-line-height", ("--line-height-normal",), ("--line-height-normal",)),
    ("--md-p-spacing", ("--p-spacing",), ("--p-spacing",)),
    ("--md-title-font", ("--inline-title-font",), ("--inline-title-font",)),
    ("--md-title-size", ("--inline-title-size",), ("--inline-title-size",)),
    ("--md-title-color", ("--inline-title-color",), ("--inline-title-color",)),
    ("--md-title-weight", ("--inline-title-weight",), ("--inline-title-weight",)),
    ("--md-title-style", ("--inline-title-style",), ("--inline-title-style",)),
    *[(f"--md-h{n}-{part}", (f"--h{n}-{part}",), (f"--h{n}-{part}",))
      for n in range(1, 7) for part in ("font", "size", "color", "weight", "style", "line-height")],
    ("--md-bold-color", ("--bold-color",), ("--bold-color",)),
    ("--md-bold-weight", ("--bold-weight",), ("--bold-weight",)),
    ("--md-italic-color", ("--italic-color",), ("--italic-color",)),
    ("--md-highlight-bg", ("--highlight-background", "--text-highlight-bg"), ("--text-highlight-bg",)),   # 1.14 : --highlight-background
    ("--md-tag-color", ("--tag-color",), ("--tag-color",)),
    ("--md-tag-bg", ("--tag-background",), ("--tag-background",)),
    ("--md-link-color", ("--link-color",), ("--link-color", "--link-external-color")),
    ("--md-link-decoration", ("--link-decoration",), ("--link-decoration", "--link-external-decoration")),
    ("--md-link-hover-decoration", ("--link-decoration-hover",),
     ("--link-decoration-hover", "--link-external-decoration-hover")),
    ("--md-link-unresolved-opacity", ("--link-unresolved-opacity",), ("--link-unresolved-opacity",)),
    ("--md-list-indent", ("--list-indent",), ("--list-indent",)),
    ("--md-list-spacing", ("--list-spacing",), ("--list-spacing",)),
    ("--md-number-color", ("--list-marker-color",), ()),
    ("--md-checkbox-color", ("--checkbox-color",), ("--checkbox-color",)),
    ("--md-checkbox-size", ("--checkbox-size",), ("--checkbox-size",)),
    ("--md-task-done-decoration", ("--checklist-done-decoration",), ("--checklist-done-decoration",)),
    ("--md-task-done-color", ("--checklist-done-color",), ("--checklist-done-color",)),
    ("--md-quote-color", ("--blockquote-color",), ("--blockquote-color",)),
    ("--md-quote-bg", ("--blockquote-background-color",), ("--blockquote-background-color",)),
    ("--md-quote-style", ("--blockquote-font-style",), ("--blockquote-font-style",)),
    ("--md-callout-title-color", ("--callout-title-color",), ("--callout-title-color",)),
    ("--md-callout-radius", ("--callout-radius",), ("--callout-radius",)),
    ("--md-code-inline-font", ("--font-monospace", "--font-monospace-theme"), ()),
    ("--md-codeblock-font", ("--font-monospace", "--font-monospace-theme"), ("--font-monospace-theme",)),
    ("--md-codeblock-bg", ("--code-background",), ("--code-background",)),
    ("--md-codeblock-color", ("--code-normal",), ("--code-normal",)),
    ("--md-syntax-comment", ("--code-comment",), ("--code-comment",)),
    ("--md-syntax-keyword", ("--code-keyword",), ("--code-keyword",)),
    ("--md-syntax-string", ("--code-string",), ("--code-string",)),
    ("--md-syntax-number", ("--code-value",), ("--code-value",)),
    ("--md-syntax-def", ("--code-function",), ("--code-function",)),
    ("--md-syntax-operator", ("--code-operator",), ("--code-operator",)),
    ("--md-syntax-property", ("--code-property",), ("--code-property",)),
    ("--md-syntax-tag", ("--code-tag",), ("--code-tag",)),
    ("--md-syntax-meta", ("--code-important",), ("--code-important",)),
    ("--md-table-grid", ("--table-border-color",), ("--table-border-color",)),
    ("--md-table-grid-width", ("--table-border-width",), ()),
    ("--md-table-cell-bg", ("--table-background",), ("--table-background",)),
    ("--md-table-alt-bg", ("--table-row-alt-background",), ("--table-row-alt-background",)),
    ("--md-table-head-bg", ("--table-header-background",), ("--table-header-background",)),
    ("--md-table-head-color", ("--table-header-color",), ("--table-header-color",)),
    ("--md-table-head-weight", ("--table-header-weight",), ("--table-header-weight",)),
    ("--md-table-head-font", ("--table-header-font",), ("--table-header-font",)),
    ("--md-table-head-size", ("--table-header-size",), ("--table-header-size",)),
    ("--md-table-color", ("--table-text-color",), ("--table-text-color",)),
    ("--md-table-size", ("--table-text-size",), ("--table-text-size",)),
    ("--md-hr-color", ("--hr-color",), ("--hr-color",)),
    ("--md-hr-thickness", ("--hr-thickness",), ("--hr-thickness",)),
    ("--md-caret", ("--caret-color",), ("--caret-color",)),
]
OBSIDIAN_VARIABLES = {name: reads for name, reads, _writes in _OBSIDIAN}
# Polices des titres laissees vides dans les reglages : celle du texte, comme dans Obsidian (--h1-font: inherit).
_INHERIT_TEXT_FONT = ("md_title", *[f"md_h{n}" for n in range(1, 7)])


def _inherits_text_font(values: dict, prefix: str) -> bool:
    label = str(_get(values, f"{prefix}_font_family") or "").strip()
    return not label or label == "Systeme"


def linked_variables(values: dict) -> dict:
    """`variables` reliees a Obsidian : `var(--obsidian, <reglage>)` pour chaque variable de `_OBSIDIAN`."""
    out = variables(values)
    v = values or {}
    for prefix in _INHERIT_TEXT_FONT:
        if _inherits_text_font(v, prefix):
            out[f"--md-{prefix[3:]}-font"] = "var(--md-text-font)"
    for name, reads in OBSIDIAN_VARIABLES.items():
        if name in out:
            value = out[name]
            for obsidian in reversed(reads):
                value = f"var({obsidian}, {value})"
            out[name] = value
    border = out.get("--md-quote-border-left", "")
    if not border.startswith("0 "):
        # Bordure gauche des citations : epaisseur et couleur d'Obsidian si la feuille les donne.
        width, _solid, color = border.split(" ", 2)
        out["--md-quote-border-left"] = (f"var(--blockquote-border-thickness, {width}) solid "
                                         f"var(--blockquote-border-color, {color})")
    return out


def theme_class(values: dict) -> str:
    """« theme-dark » ou « theme-light » d'apres le fond (classe du <body>, comme dans Obsidian : les themes
    rangent leurs couleurs sous ces classes)."""
    color = css_color(_get(values or {}, "md_bg_color"), "#1b1c1d").lstrip("#")
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "theme-dark"
    return "theme-light" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 140 else "theme-dark"


# Ordre des couches : structure (protegee), habillage des reglages, feuille choisie (prioritaire sur l'habillage).
LAYER_ORDER = "@layer md-structure, md-theme, md-user;"


def user_css(values: dict) -> tuple[Path | None, str]:
    """Feuille choisie dans Reglages > Markdown > CSS : (chemin si elle est LISIBLE, etat en clair). Absente,
    illisible, pas un fichier : None et le module garde son style integre (le fichier n'est jamais modifie)."""
    raw = str((values or {}).get("md_css_path") or "").strip().strip('"')
    if not raw:
        return None, "Style intégré (aucun fichier choisi)."
    try:
        path = Path(os.path.expandvars(raw)).expanduser()
        if not path.is_absolute():
            return None, f"Chemin non absolu : « {raw} ». Style intégré utilisé."
        if not path.is_file():
            return None, f"Fichier introuvable : « {path.name} ». Style intégré utilisé."
        with open(path, "rb") as handle:
            handle.read(1)
    except (OSError, ValueError) as exc:
        return None, f"Fichier illisible ({exc.__class__.__name__}). Style intégré utilisé."
    return path, f"Feuille chargée : « {path.name} » (prioritaire sur les réglages pour ce qu'elle définit)."


def user_css_url(values: dict) -> str:
    """Adresse de la feuille choisie (avec sa date : une feuille modifiee est relue), ou « » (style integre)."""
    path, _status = user_css(values)
    if path is None:
        return ""
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return f"{path.as_uri()}?v={stamp}"


def import_rule(url: str, layer: str) -> str:
    """`@import` d'une feuille dans une couche (vide = rien)."""
    return f'@import url("{url}") layer({layer});' if url else ""


# -- Export : feuille utilisable dans Obsidian (snippet) -------------------------------------------------------------
EXPORT_MARKER = "pipeline-browser:markdown-export"


def _export_rules(v: dict, out: dict) -> list[str]:
    """Regles sur les classes d'Obsidian pour ce que ses variables ne couvrent pas (espacements, tableaux, blocs…).
    Les memes classes existent dans le module (alias poses par la page) : la feuille exportee s'y recharge telle
    quelle."""
    rules = []

    def add(selectors, body):
        body = [(prop, value) for prop, value in body if value not in (None, "")]
        if body:
            rules.append(f"{selectors} {{\n" + "".join(f"  {prop}: {value};\n" for prop, value in body) + "}")

    rendered, source = ".markdown-rendered", ".markdown-source-view.mod-cm6"
    add(".inline-title", [("display", None if _get(v, "md_title_enabled") else "none"),
                          ("margin-bottom", out["--md-title-spacing"])])
    for n in range(1, 7):
        add(f"{rendered} h{n}", [("margin-top", out[f"--md-h{n}-before"]), ("margin-bottom", out[f"--md-h{n}-after"])])
        add(f"{source} .cm-line.HyperMD-header-{n}", [("padding-top", out[f"--md-h{n}-before"]),
                                                       ("padding-bottom", out[f"--md-h{n}-after"])])
    add(f"{rendered} del, {rendered} s, {source} .cm-strikethrough",
        [("color", out["--md-strike-color"]), ("text-decoration-color", out["--md-strike-line"]),
         ("background-color", out["--md-strike-bg"])])
    add(f"{rendered} mark, {source} .cm-highlight", [("color", out["--md-highlight-color"])])
    link_font = None if out["--md-link-font"] == "inherit" else out["--md-link-font"]
    add(f"{rendered} a.internal-link, {rendered} a.external-link, {source} .cm-hmd-internal-link, "
        f"{source} .cm-link, {source} .cm-url",
        [("font-family", link_font), ("letter-spacing", out["--md-link-letter-spacing"])])
    # Puces de l'edition (meme principe que fabrice.css : le tiret est masque, la puce dessinee par ::before).
    add(f"{source} .list-bullet", [("font-size", "0"), ("color", "transparent")])
    add(f"{source} .list-bullet::after", [("display", "none")])
    for n in (1, 2, 3):
        selector = f"{source} .cm-list-{n} .list-bullet::before" if n > 1 else f"{source} .list-bullet::before"
        add(selector, [("content", out[f"--md-bullet-{n}-char"]), ("color", out[f"--md-bullet-{n}-color"]),
                       ("font-size", out[f"--md-bullet-{n}-size"])])
    add(f"{rendered} blockquote", [("padding", out["--md-quote-padding"]), ("border-radius", out["--md-quote-radius"]),
                                   ("margin", f"{out['--md-quote-spacing']} 0")])
    add(".callout", [("background-color", out["--md-callout-bg"]), ("border", "none"),
                     ("border-left", out["--md-callout-border"]), ("border-radius", out["--md-callout-radius"])])
    add(".callout-title", [("color", out["--md-callout-title-color"])])
    add(f"{rendered} :not(pre) > code, {source} .cm-inline-code:not(.cm-formatting)",
        [("font-family", out["--md-code-inline-font"]), ("font-size", out["--md-code-inline-size"]),
         ("color", out["--md-code-inline-color"]), ("font-weight", out["--md-code-inline-weight"]),
         ("background-color", out["--md-code-inline-bg"]), ("border-radius", out["--md-code-inline-radius"]),
         ("padding", out["--md-code-inline-padding"])])
    add(f"{rendered} pre", [("background-color", out["--md-codeblock-bg"]), ("padding", out["--md-codeblock-padding"]),
                            ("border-radius", out["--md-codeblock-radius"]),
                            ("margin", f"{out['--md-codeblock-spacing']} 0"),
                            *[(f"border-{side}", out[f"--md-codeblock-border-{side}"]) for side in _SIDES]])
    add(f"{rendered} pre code, {source} .HyperMD-codeblock",
        [("font-family", out["--md-codeblock-font"]), ("font-size", out["--md-codeblock-size"]),
         ("font-weight", out["--md-codeblock-weight"]), ("line-height", out["--md-codeblock-line-height"])])
    add(f"{source} .HyperMD-codeblock", [("background-color", out["--md-codeblock-bg"])])
    corners = out["--md-codeblock-radius"].split()
    add(f"{source} .HyperMD-codeblock-begin", [("border-top-left-radius", corners[0]),
                                               ("border-top-right-radius", corners[1])])
    add(f"{source} .HyperMD-codeblock-end", [("border-bottom-right-radius", corners[2]),
                                             ("border-bottom-left-radius", corners[3])])
    add(f"{rendered} table", [("border-collapse", "separate"), ("border-spacing", out["--md-table-grid-width"]),
                              ("background-color", out["--md-table-grid"]), ("border", "none"),
                              ("border-radius", out["--md-table-radius"]), ("overflow", "hidden"),
                              ("margin", f"{out['--md-table-spacing']} 0")])
    add(f"{rendered} th, {rendered} td", [("padding", out["--md-table-cell-padding"]), ("border", "none")])
    add(f"{rendered} td", [("background-color", out["--md-table-cell-bg"])])
    marked_cells = f"{rendered} td:has(span.pb-table-cell-bg), {rendered} th:has(span.pb-table-cell-bg)"
    add(marked_cells, [("overflow", "hidden"), ("padding", "0")])
    add(f"{rendered} td span.pb-table-cell-bg, {rendered} th span.pb-table-cell-bg",
        [("display", "block"), ("width", "100%"), ("box-sizing", "border-box")])
    add(f"{rendered} tbody tr:nth-child(even) td", [("background-color", out["--md-table-alt-bg"])])
    add(f"{rendered} hr", [("margin", f"{out['--md-hr-spacing']} 0")])
    add(f"{rendered} img, {source} img",
        [("max-width", out["--md-image-max-width"]), ("border-radius", out["--md-image-radius"])])
    return rules


def obsidian_snippet(values: dict) -> str:
    """Feuille CSS pour Obsidian (a ranger dans <coffre>/.obsidian/snippets) d'apres les reglages Markdown :
    variables documentees d'Obsidian + regles sur ses classes. Rechargee dans le module, elle redonne le meme
    habillage (memes classes, memes variables)."""
    v = values or {}
    out = variables(v)
    inherited = {f"--md-{prefix[3:]}-font" for prefix in _INHERIT_TEXT_FONT if _inherits_text_font(v, prefix)}
    lines = []
    for name, _reads, writes in _OBSIDIAN:
        value = out.get(name)
        if value is None or name in inherited:        # police du texte : celle d'Obsidian, pas une copie figee
            continue
        for obsidian in writes:
            lines.append(f"  {obsidian}: {value};")
    border = out["--md-quote-border-left"]
    if not border.startswith("0 "):
        width, _solid, color = border.split(" ", 2)
        lines += [f"  --blockquote-border-thickness: {width};", f"  --blockquote-border-color: {color};"]
    head = (f"/* {EXPORT_MARKER}\n"
            "   Habillage Markdown exporte par Pipeline Browser (Reglages > Markdown). A copier dans\n"
            "   <coffre>/.obsidian/snippets puis activer dans Obsidian (Apparence > Extraits CSS).\n"
            "   Peut etre recharge dans Pipeline Browser (Reglages > Markdown > CSS).\n"
            "   Non exporte (sans equivalent dans Obsidian) : barre d'outils, fichiers de code, numeros de ligne,\n"
            "   puces du mode lecture. La police et la taille du texte choisies dans Obsidian (Apparence) passent\n"
            "   avant celles de ce fichier. */\n")
    return (head + "body.theme-dark, body.theme-light {\n" + "\n".join(lines) + "\n}\n\n"
            + "\n\n".join(_export_rules(v, out)) + "\n")


def is_exported_file(path: Path) -> bool:
    """Fichier produit par `export_obsidian_css` (on ne remplace jamais une feuille ecrite par l'utilisateur)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return EXPORT_MARKER in handle.read(400)
    except OSError:
        return False


def export_obsidian_css(values: dict, path: Path) -> None:
    """Ecrit la feuille d'export. Refuse (ValueError) de remplacer un fichier qui n'a pas ete produit par l'export."""
    path = Path(path)
    if path.exists() and not is_exported_file(path):
        raise ValueError(f"« {path.name} » n'a pas été produit par Pipeline Browser : il n'est pas remplacé.")
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(obsidian_snippet(values), encoding="utf-8")
    os.replace(tmp, path)
