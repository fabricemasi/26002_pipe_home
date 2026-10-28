"""Module Markdown / code (demande de l'utilisateur, octobre 2026 : remplace le module Obsidian et l'ancien mode
« Editeur de texte ») : notes .md en lecture et en edition mises en forme, fichiers texte et de code avec coloration
syntaxique, barre Editing Toolbar, apparence reglee dans l'onglet « Markdown » des reglages.

- `pane.py` : le panneau Qt (une QWebEngineView prechargee) et tout ce qui touche au disque.
- `style.py` : reglages `md_*` -> variables CSS (source unique de l'apparence, inspecteur compris).
- `web/` : la page (base.css, app.js, editor.js, toolbar.js, highlight.js) et CodeMirror 5 (vendor/, licence MIT).
- `toolbar.json` : commandes, icones et couleurs de la barre d'outils.
Le rendu Markdown -> HTML et la lecture / ecriture fideles sont dans `fm_markdown/preview.py` (partages avec
l'inspecteur). Aucune dependance vers la fenetre principale."""
from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# Fichiers que le module sait ouvrir (bouton « Éditeur » de la barre) : notes, texte, code, configurations.
TEXT_EXTENSIONS = {
    ".md", ".markdown", ".txt", ".text", ".log", ".csv", ".tsv", ".rst", ".srt",
    ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".jsonc", ".html", ".htm", ".css",
    ".scss", ".less", ".xml", ".svg", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1", ".vex", ".vfl", ".osl", ".glsl", ".hlsl", ".h", ".hh", ".hpp",
    ".c", ".cc", ".cpp", ".cxx", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".lua", ".r", ".sql", ".swift",
    ".mel", ".nk", ".usda", ".tcl", ".pl", ".diff", ".patch", ".dockerfile", ".gitignore", ".editorconfig",
}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}


def web_dir() -> Path:
    return PACKAGE_DIR / "web"


def is_text_file(path) -> bool:
    """Fichier que le module ouvre comme texte (extension connue ; un binaire est refuse a l'ouverture)."""
    if path is None:
        return False
    path = Path(path)
    suffix = path.suffix.lower() or path.name.lower()
    return suffix in TEXT_EXTENSIONS or (not path.suffix and path.name.lower() in ("dockerfile", "makefile"))


def is_markdown(path) -> bool:
    return Path(path).suffix.lower() in MARKDOWN_EXTENSIONS
