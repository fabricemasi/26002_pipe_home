"""Orthographe du module Markdown / texte (demande de l'utilisateur, 2026-11-12) : un bouton des barres « Markdown » et
« Texte » souligne les fautes, le clic droit sur un mot souligné propose des corrections.

- Moteur : le correcteur INTÉGRÉ de Chromium (QtWebEngine). Il travaille dans ses propres processus, en fond : aucun
  coût sur le fil de l'interface, rien à refaire à chaque frappe.
- Dictionnaire : `dictionaries/fr-FR.bdic` (Hunspell français compilé par Chromium, le même que celui de Chrome).
  Absent : recopié de celui que Chrome a téléchargé, s'il existe. Le dossier est donné à QtWebEngine par
  QTWEBENGINE_DICTIONARIES_PATH, posé par `fm_markdown/__init__.py` (avant toute page web).
- Page : l'option « spellcheck » de CodeMirror (éditeur en contenteditable) ; seulement sur les notes et les fichiers
  de texte (`checks`), jamais sur le code.
- Clic droit : `QWebEngineView.lastContextMenuRequest()` donne le mot fautif et les suggestions ; le remplacement est
  fait par la page dans CodeMirror (annulable par Ctrl + Z).
- « Ajouter au dictionnaire » : Qt n'offre aucun accès au dictionnaire personnel de Chromium. Les mots vont dans
  `md_spell_words` (état temps réel) ; la page les entoure d'un `<span spellcheck="false">` (calque CodeMirror,
  `Editor.setKnownWords`) : Chromium ne les souligne plus."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fm_markdown import PACKAGE_DIR, is_markdown

LANGUAGE = "fr-FR"
DICT_DIR = PACKAGE_DIR / "dictionaries"
PROSE_EXTENSIONS = {".txt", ".text", ".rst", ".srt"}
MAX_SUGGESTIONS = 8

_enabled_profiles: set[int] = set()


def checks(path) -> bool:
    """Fichier dont l'orthographe est vérifiée : notes et texte, jamais le code."""
    if path is None:
        return False
    path = Path(path)
    return is_markdown(path) or path.suffix.lower() in PROSE_EXTENSIONS


def _chrome_dictionaries() -> list[Path]:
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    if not base.is_dir():
        return []
    found = sorted(base.glob(f"{LANGUAGE}-*.bdic")) + sorted((base / "Dictionaries").glob(f"{LANGUAGE}-*.bdic"))
    return [p for p in found if p.is_file()]


def ensure_dictionary() -> bool:
    """Le dictionnaire est en place (recopié de Chrome s'il manque)."""
    target = DICT_DIR / f"{LANGUAGE}.bdic"
    if target.is_file():
        return True
    for source in _chrome_dictionaries():
        try:
            DICT_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            return True
        except OSError:
            continue
    return False


def enable(profile) -> bool:
    """Allume le correcteur du profil (une fois) ; faux si aucun dictionnaire n'est disponible."""
    if id(profile) in _enabled_profiles:
        return True
    if not ensure_dictionary():
        return False
    profile.setSpellCheckLanguages([LANGUAGE])
    profile.setSpellCheckEnabled(True)
    _enabled_profiles.add(id(profile))
    return True


def menu_entries(word: str, suggestions: list[str]) -> tuple[list, list[str]]:
    """Lignes du menu du clic droit (titre = le mot fautif) et suggestions cliquables, dans l'ordre ; la ligne
    cliquable suivante (rang `len(choices)`) = « Ajouter au dictionnaire »."""
    choices = [s for s in suggestions if s and s != word][:MAX_SUGGESTIONS]
    entries: list = [{"section": f"« {word} »"}]
    if choices:
        entries += [{"title": s} for s in choices]
    else:
        entries.append({"section": "Aucune suggestion"})
    entries += ["-", {"title": "Ajouter au dictionnaire"}]
    return entries, choices


def add_word(words, word: str) -> list[str]:
    """Dictionnaire personnel (`md_spell_words`) avec `word` en plus (aucun doublon)."""
    out = [str(w) for w in words if str(w).strip()] if isinstance(words, (list, tuple)) else []
    word = str(word).strip()
    if word and word not in out:
        out.append(word)
    return out
