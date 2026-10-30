"""Inventaire fm_theme (étape 1, docs/agents/fm_theme.md) : classe chaque clé de DEFAULT_SETTINGS en
« theme » (aspect générique -> fm_theme), « propre » (aspect d'un élément propre à fm_browser -> références
vers fm_theme) ou « fonctionnement » (reste dans fm_browser), puis écrit docs/agents/fm_theme_inventaire.md.

Lancer depuis la racine : `python tools/inventaire_reglages.py`. Le classement se fait par FAMILLE (préfixe),
puis par clé dans les familles mixtes (mots de la clé). Les cas ajustés à la main sont dans EXCEPTIONS.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]
import _isolate  # noqa: E402,F401  (réglages redirigés vers des copies)
import settings_store  # noqa: E402

THEME, PROPRE, FONC = "theme", "propre", "fonctionnement"
LABELS = {THEME: "Aspect générique → fm_theme", PROPRE: "Aspect propre à fm_browser → références vers fm_theme",
          FONC: "Fonctionnement → reste dans fm_browser"}

# Familles d'aspect GÉNÉRIQUE (types d'éléments de fm_theme) : préfixe -> type d'élément.
THEME_FAMILIES = {
    "colors": "palette", "font_": "rôles de texte", "title_": "titres (niveaux 1-5)",
    "toggle1_": "toggle", "toggle2_": "toggle", "toggle_styles": "toggle", "toggle_custom_styles": "toggle",
    "toggle_style": "toggle", "slider_": "slider", "input_": "champ de saisie", "button_": "bouton",
    "table_": "tableau", "tabs_": "onglets", "ctx_": "menu contextuel", "extra_": "fenêtre additionnelle",
    "window_radius": "fenêtre",
}
# Familles d'aspect PROPRES à fm_browser (restent dans fm_browser, valeurs -> références) ; leurs clés de
# fonctionnement sont reconnues par les mots de la clé (voir LOOK_WORDS).
PROPRE_FAMILIES = {
    # Colonnes Miller : propres à fm_browser (choix de l'utilisateur, 2026-10-29).
    "item_": "colonne (lignes)", "header_": "colonne (entête)", "column_": "colonne (cadre)",
    "crumb_": "cheminement", "navbar_": "barre de navigation", "step_": "badges d'étapes",
    "resize_": "badge de redimensionnement", "shortcut_": "texte des raccourcis",
    "preview_": "carte d'aperçu", "viewer_": "visionneuse", "md_": "Markdown", "board_": "board / CAD",
    "video_": "vidéo",
}
# Mots qui désignent un aspect (couleur, police, géométrie de dessin).
LOOK_WORDS = {
    "color", "colors", "bg", "family", "bold", "italic", "smoothing", "border", "thickness", "radius",
    "padding", "margin", "spacing", "shadow", "opacity", "weight", "height", "width", "size", "underline",
    "strike", "font", "uppercase", "gap", "indent", "char", "kind", "skin", "icon", "line", "fg", "text",
    "offset", "x", "y", "position", "justify", "style", "intensity", "ratio", "checker", "black", "white",
    "comment", "keyword", "string", "number", "def", "variable", "secondary", "animated", "frame",
    "space", "align", "inner", "bottom", "separator",
}
# Ajustements à la main (clé -> (catégorie, raison)) : priment sur tout le reste.
EXCEPTIONS: dict[str, tuple[str, str]] = {
    "table_dims": (FONC, "disposition (largeurs des colonnes des tableaux)"),
    "table_rows_movable": (FONC, "comportement (Ctrl + glisser des lignes)"),
    "slider_ranges": (FONC, "plages des curseurs choisies au clic droit"),
    "title_order": (FONC, "disposition (ordre des titres)"),
    "toggle_style_overrides": (FONC, "override d'élément (reste côté appli)"),
    "column_type_overrides": (FONC, "override d'élément (reste côté appli)"),
    "column_type_override_enabled": (FONC, "override d'élément (reste côté appli)"),
    "column_overrides_by_title": (FONC, "override d'élément (reste côté appli)"),
    "column_override_enabled_by_title": (FONC, "override d'élément (reste côté appli)"),
    "font_table_columns": (FONC, "disposition du tableau des polices"),
    "ui_scale": (THEME, "échelle générale de l'interface"),
    "row_templates": (THEME, "gabarits des lignes des fenêtres de réglages (choix de l'utilisateur, 2026-10-29)"),
    # Mots d'aspect dans le nom, mais comportement ou contenu du document :
    **{k: (FONC, "comportement") for k in (
        "md_tab_size", "md_line_numbers", "video_moodboard_proxy_width", "video_analysis_exclude_black",
        "video_analysis_exclude_white", "video_match_lut_size", "video_match_intensity", "video_reset_position",
        "video_lut_position", "board_grid_origin_x", "board_grid_origin_y")},
    **{k: (FONC, "unités du dessin CAD (contenu, pas aspect)") for k in (
        "board_cad_dim_text", "board_cad_text_height")},
    "board_cad_magnet_radius": (FONC, "comportement (portée de l'aimant du réticule)"),
    # Sans mot d'aspect dans le nom, mais dessinent la grille du board :
    **{k: (PROPRE, "board / CAD") for k in (
        "board_grid_fade_start", "board_grid_fade_full", "board_grid_levels", "board_grid_axes")},
}


def family_of(key: str, families: dict[str, str]) -> str | None:
    """Préfixe de `families` le plus long qui correspond à `key` (clé exacte ou préfixe terminé par « _ »)."""
    best = None
    for prefix in families:
        hit = key == prefix if not prefix.endswith("_") else key.startswith(prefix)
        if hit and (best is None or len(prefix) > len(best)):
            best = prefix
    return best


def is_look(key: str, value) -> bool:
    """Vrai si la clé décrit un aspect : un mot d'aspect dans son nom, ou une valeur couleur « #… »."""
    words = set(key.split("_")[1:]) - {"enabled", "linked", "override"}
    if isinstance(value, str) and value.startswith("#"):
        return True
    return bool(words & LOOK_WORDS)


def classify(key: str, value) -> tuple[str, str, str]:
    """(catégorie, famille, raison) d'une clé."""
    if key in EXCEPTIONS:
        cat, why = EXCEPTIONS[key]
        return cat, family_of(key, {**THEME_FAMILIES, **PROPRE_FAMILIES}) or "divers", why
    fam = family_of(key, THEME_FAMILIES)
    if fam:
        return THEME, fam, THEME_FAMILIES[fam]
    fam = family_of(key, PROPRE_FAMILIES)
    if fam:
        if is_look(key, value):
            return PROPRE, fam, PROPRE_FAMILIES[fam]
        return FONC, fam, f"{PROPRE_FAMILIES[fam]} : comportement"
    return FONC, key.split("_")[0] + "_", "fonctionnement"


def main() -> None:
    rows = [(k, *classify(k, v)) for k, v in settings_store.DEFAULT_SETTINGS.items()]
    by_cat: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for key, cat, fam, why in rows:
        by_cat[cat][fam].append((key, why))
    out = ["# Inventaire des réglages pour fm_theme (étape 1)", "",
           "Produit par `python tools/inventaire_reglages.py` (ne pas éditer à la main : corriger le script, "
           "`EXCEPTIONS` ou les familles, puis relancer). Plan : `fm_theme.md`, « Ordre de migration ».", "",
           "| Catégorie | Clés |", "|---|---|"]
    for cat in (THEME, PROPRE, FONC):
        out.append(f"| {LABELS[cat]} | {sum(len(v) for v in by_cat[cat].values())} |")
    for cat in (THEME, PROPRE, FONC):
        out += ["", f"## {LABELS[cat]}", ""]
        for fam in sorted(by_cat[cat]):
            items = by_cat[cat][fam]
            whys = sorted({w for _, w in items})
            out.append(f"<details><summary><code>{fam}</code> : {len(items)} clés ({' ; '.join(whys)})</summary>")
            out += ["", ", ".join(f"`{k}`" for k, _ in items), "", "</details>"]
    path = ROOT / "docs" / "agents" / "fm_theme_inventaire.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    for cat in (THEME, PROPRE, FONC):
        print(cat, sum(len(v) for v in by_cat[cat].values()))


if __name__ == "__main__":
    main()
