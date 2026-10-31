"""Module fm_font : éditeur typographique (projets UFO 3 + Designspace, compilation OTF / TTF / WOFF / WOFF2 /
variable). Carte du module, décisions et PASSATION : docs/agents/fm_font.md.

Couches (chaque fichier n'importe que ceux qui le précèdent) :
- MODÈLE sans Qt : `glyph_info`, `undo`, `document`, `contours`, `geometry`, `shapes`, `calligraphy`, `metrics`,
  `kerning`, `components`, `features`, `shaping`, `interpolation`, `compile`, `importer`, `validation`.
- INTERFACE Qt : `render`, `canvas`, `tools`, `glyph_grid`, `preview`, `panels`, `pane`.

Le module n'importe RIEN de la fenêtre principale : elle lui pose des `HOOKS` (`fm_font.pane.HOOKS`)."""
from __future__ import annotations

from pathlib import Path

# Sources ouvertes par le module (un .ufo est un DOSSIER) et polices compilées importées (jamais réécrites).
SOURCE_SUFFIXES = (".designspace", ".ufo", ".ufoz")
BINARY_SUFFIXES = (".ttf", ".otf", ".woff", ".woff2")


def is_font_source(path) -> bool:
    return Path(path).suffix.lower() in SOURCE_SUFFIXES


def is_font_file(path) -> bool:
    """Fichier (ou dossier .ufo) que le module sait ouvrir : source ou police compilée (importée)."""
    suffix = Path(path).suffix.lower()
    return suffix in SOURCE_SUFFIXES or suffix in BINARY_SUFFIXES
