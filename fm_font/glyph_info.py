"""Informations Unicode des glyphes (sans Qt) : nom <-> code, catégorie, écriture, jeux de caractères de
référence (glyphes manquants). S'appuie sur fontTools.agl (noms AGL) et fontTools.unicodedata (écritures)."""
from __future__ import annotations

import unicodedata
from functools import lru_cache

from fontTools import agl
from fontTools import unicodedata as ft_unicodedata

# Catégories générales Unicode regroupées comme dans les éditeurs de polices.
CATEGORY_GROUPS = {
    "Lettre": ("Lu", "Ll", "Lt", "Lm", "Lo"),
    "Marque": ("Mn", "Mc", "Me"),
    "Chiffre": ("Nd", "Nl", "No"),
    "Ponctuation": ("Pc", "Pd", "Ps", "Pe", "Pi", "Pf", "Po"),
    "Symbole": ("Sm", "Sc", "Sk", "So"),
    "Séparateur": ("Zs", "Zl", "Zp"),
    "Autre": ("Cc", "Cf", "Cs", "Co", "Cn"),
}
_GROUP_OF = {cat: group for group, cats in CATEGORY_GROUPS.items() for cat in cats}

# Jeux de caractères de référence pour « glyphes manquants » (codes Unicode).
CHARSETS = {
    "Latin de base": [0x20] + list(range(0x21, 0x7F)),
    "Latin-1": list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)),
    "Français": list(range(0x20, 0x7F)) + [0xA0, 0xAB, 0xBB, 0xC0, 0xC2, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB, 0xCE,
                                           0xCF, 0xD4, 0xD9, 0xDB, 0xDC, 0xE0, 0xE2, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
                                           0xEB, 0xEE, 0xEF, 0xF4, 0xF9, 0xFB, 0xFC, 0xFF, 0x152, 0x153, 0x178,
                                           0x2019, 0x201C, 0x201D, 0x2026, 0x20AC],
}


@lru_cache(maxsize=4096)
def name_for_unicode(code: int) -> str:
    """Nom de glyphe conventionnel (AGL, sinon uniXXXX / uXXXXX)."""
    name = agl.UV2AGL.get(code)
    if name:
        return name
    return f"uni{code:04X}" if code <= 0xFFFF else f"u{code:05X}"


@lru_cache(maxsize=4096)
def unicode_for_name(name: str) -> int | None:
    """Code déduit d'un nom de glyphe (AGL, uniXXXX, uXXXX[X]) ; None pour un nom sans code (ligature, .alt…)."""
    if "." in name.lstrip(".") or "_" in name or name.startswith("."):
        return None                                   # variante (n.sc), ligature (f_i), .notdef : pas de code
    text = agl.toUnicode(name)
    return ord(text) if len(text) == 1 else None


@lru_cache(maxsize=8192)
def category(code: int | None) -> str:
    if code is None:
        return "Sans Unicode"
    return _GROUP_OF.get(unicodedata.category(chr(code)), "Autre")


@lru_cache(maxsize=8192)
def script(code: int | None) -> str:
    if code is None:
        return ""
    return ft_unicodedata.script_name(ft_unicodedata.script(chr(code)), default="Inconnu")


@lru_cache(maxsize=8192)
def char_name(code: int | None) -> str:
    if code is None:
        return ""
    return unicodedata.name(chr(code), "")


def is_mark(code: int | None) -> bool:
    return code is not None and unicodedata.category(chr(code)) in ("Mn", "Mc", "Me")


def decomposition(code: int) -> list[int]:
    """Décomposition canonique (é -> e + U+0301), vide si le caractère n'en a pas."""
    text = unicodedata.normalize("NFD", chr(code))
    return [ord(c) for c in text] if len(text) > 1 else []
