"""Carte des réglages : section de la fenêtre de réglages -> groupe du catalogue -> clés, plus « préfixe -> code qui
l'applique ». Régénère `docs/agents/carte_reglages.md` (à relancer après un ajout ou un déplacement de section) :

    python tools/carte_reglages.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import _isolate  # noqa: E402,F401  (jamais les vrais réglages)

import settings_window_v2 as v2  # noqa: E402
from fm_theme import presets as tp  # noqa: E402

# Préfixe de clé -> où la valeur est appliquée (à tenir à jour à la main ; le reste est généré).
APPLIED = [
    ("navbar_", "main_window/title_bar.py (`refresh_sizes`, `refresh_look`) ; chemin rapide `refresh_navbar` (main_window/chrome.py)"),
    ("crumb_", "main_window/title_bar.py (`refresh_crumbs`, `_crumb_look`)"),
    ("statusbar_", "fm_theme/status_bar.py (`apply_status_bar`) via `ChromeMixin.refresh_status_bar`"),
    ("extra_window_", "settings_window_v2.seed_extra_window_look, fm_theme/window.py (`install_extra_window`)"),
    ("window_border", "browser_core.apply_window_border, main_window/helpers.CentralFrame"),
    ("button_ / input_ / tabs_", "fm_theme/style.build_stylesheet, settings_theme.apply_input_look, _TabStrip"),
    ("slider_ / title_ / table_ / toggle / ctx_ / palette_", "settings_link._restyle_bricks (briques fm_theme)"),
    ("colors / font_", "app_style.apply_all_settings -> refresh_colors / refresh_fonts"),
    ("item_ / header_ / column_", "column.py, row_delegates.py, column_parts/appearance.py"),
    ("preview_ / viewer_", "capture_widgets.py, preview_column.py, fm_visionneuse/"),
    ("md_", "fm_markdown/pane.py (`apply_settings`), fm_markdown/css_sync.py"),
    ("video_", "fm_video/pane.py (`apply_settings`)"),
    ("board_ / tableur_", "fm_board/ui.py (`apply_settings`) ; CAD : fm_cad/settings.py ; Photoshop : fm_photoshop/settings.py"),
    ("typo_", "fm_font/pane.py (`apply_settings`)"),
    ("auto_", "automatic_tasks.py"),
]


def _keys(group: str) -> str:
    keys = [s.key for s in v2.CATALOG.get(group, []) if not isinstance(s, str) and getattr(s, "key", None)]
    if len(keys) > 8:
        keys = keys[:8] + [f"… (+{len(keys) - 8})"]
    return ", ".join(f"`{k}`" for k in keys)


def _walk(nodes, path, out, tab):
    for node in nodes:
        here = f"{path} > {node.title}" if path else node.title
        if node.group:
            first = next((s.key for s in v2.CATALOG.get(node.group, []) if getattr(s, "key", None)), "")
            where = "fm_theme" if first and tp.theme_key(first) else "appli"
            out.append(f"| {tab} | {here} | `{node.group}` | {where} | {_keys(node.group)} |")
        _walk(node.children or (), here, out, tab)


def main() -> None:
    lines = ["# Carte des réglages (GÉNÉRÉE : `python tools/carte_reglages.py`, ne pas éditer à la main)", "",
             "Trouver en une recherche où vit un réglage : section affichée -> groupe du catalogue (`CATALOG[...]`, "
             "settings_window_v2.py ou `<paquet>/settings.py`) -> clés. « fm_theme » = la clé est enregistrée dans le "
             "preset fm_theme (`fm_theme.presets.theme_key`).", "",
             "## Qui applique quoi", "", "| Préfixe | Appliqué par |", "|---|---|"]
    lines += [f"| `{p}` | {w} |" for p, w in APPLIED]
    lines += ["", "## Sections", "", "| Onglet | Section | Groupe | Stockage | Clés |", "|---|---|---|---|---|"]
    tabs = [("General", None), (v2.THEME_TAB, None)] + [t for scopes in v2.MODULE_SCOPES.values() for t in scopes
                                                         if t[0] != v2.THEME_TAB]
    for tab, _x in tabs:
        _walk(v2.tab_tree(tab), "", lines, v2.TAB_LABELS.get(tab, tab))
    (ROOT / "docs" / "agents" / "carte_reglages.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(len(lines), "lignes")


if __name__ == "__main__":
    main()
