"""Presets fm_theme : format (numéro `FORMAT`), conversion depuis les réglages à plat, lecture / écriture.

Un preset = un thème complet, un fichier par preset dans `PRESETS_DIR` (fm_theme/presets/<nom>.json) :

    {"format": 1, "nom": "fab",
     "general": {"colors": {...}, "font_main": {...}, "ui_scale": 100, "window_radius": 8},
     "types": {"toggle": {"defaut": "toggle2", "variantes": {"toggle1": {"outer_width": 34, ...}, ...}},
               "titres": {"defaut": "standard", "variantes": {"standard": {"level1_font_size": 14, ...}}},
               ...}}

Dans une variante, les champs sont les clés de réglage SANS leur préfixe (`toggle2_outer_width` -> variante
« toggle2 », champ « outer_width » ; `title_level1_font_size` -> variante « standard » de « titres », champ
« level1_font_size »). `from_settings` puis `to_settings` rend EXACTEMENT les clés d'aspect de départ (rien
n'est perdu) ; les autres clés (fonctionnement, aspect propre à l'appli) n'entrent jamais dans un preset fm_theme.
Plan : docs/agents/fm_theme.md (étape 3). Aucun import de l'appli.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

FORMAT = 1
PRESETS_DIR = Path(__file__).resolve().parent / "presets"   # redirigé par tests/_isolate.py
STANDARD = "standard"                                         # nom de la variante unique des types sans variantes

# Valeurs générales (pas de variantes) : clés exactes, et préfixe des rôles de texte.
GENERAL_KEYS = ("colors", "ui_scale", "window_radius")
GENERAL_PREFIX = "font_"
# Types à une variante : type -> préfixe des clés.
TYPE_PREFIXES = {
    "titres": "title_", "slider": "slider_", "champ": "input_", "bouton": "button_", "tableau": "table_",
    "onglets": "tabs_", "menu": "ctx_", "fenetre": "extra_",
}
# Toggles : une variante par style (`toggle<N>_*`) ; clés propres au type : variante par défaut (`toggle_style`)
# et noms des styles (`toggle_styles`, ancienne liste `toggle_custom_styles`).
TOGGLE_RE = re.compile(r"^(toggle\d+)_(.+)$")
TOGGLE_META = {"toggle_style": "defaut", "toggle_styles": "noms", "toggle_custom_styles": "noms_anciens"}
# Clés qui ont un préfixe d'aspect mais décrivent un ÉTAT de l'appli (dispositions, plages, ordres, surcharges
# d'éléments) : elles restent dans les réglages de l'appli (inventaire validé, tools/inventaire_reglages.py).
APP_STATE_KEYS = frozenset({
    "table_dims", "table_rows_movable", "slider_ranges", "title_order", "font_table_columns",
    "toggle_style_overrides",
})


def theme_key(key: str) -> tuple[str, str, str] | None:
    """(type, variante, champ) d'une clé d'aspect ; type « general » (variante vide, champ = clé) ; None si la
    clé n'appartient pas à fm_theme."""
    if key in APP_STATE_KEYS:
        return None
    if key in GENERAL_KEYS or key.startswith(GENERAL_PREFIX):
        return "general", "", key
    if key in TOGGLE_META:
        return "toggle", "", TOGGLE_META[key]
    match = TOGGLE_RE.match(key)
    if match:
        return "toggle", match[1], match[2]
    for type_name, prefix in TYPE_PREFIXES.items():
        if key.startswith(prefix):
            return type_name, STANDARD, key[len(prefix):]
    return None


def from_settings(values: dict[str, Any], name: str) -> dict[str, Any]:
    """Preset fm_theme tiré de réglages à plat (un preset de l'appli, ou ses réglages courants)."""
    general: dict[str, Any] = {}
    types: dict[str, dict[str, Any]] = {}
    for key, value in values.items():
        where = theme_key(key)
        if where is None:
            continue
        type_name, variant, field = where
        if type_name == "general":
            general[field] = value
            continue
        entry = types.setdefault(type_name, {"defaut": None, "variantes": {}})
        if not variant:                         # clé propre au type (toggle_style, toggle_styles...)
            entry[field] = value
            continue
        entry["variantes"].setdefault(variant, {})[field] = value
    for type_name, entry in types.items():
        if entry["defaut"] is None and type_name != "toggle":
            entry["defaut"] = STANDARD
    return {"format": FORMAT, "nom": name, "general": general, "types": types}


def to_settings(preset: dict[str, Any]) -> dict[str, Any]:
    """Réglages à plat d'un preset fm_theme (inverse exact de `from_settings`)."""
    values: dict[str, Any] = dict(preset.get("general") or {})
    for type_name, entry in (preset.get("types") or {}).items():
        if type_name == "toggle":
            for key, field in TOGGLE_META.items():
                if field in entry and (field != "defaut" or entry[field] is not None):
                    values[key] = entry[field]
            for variant, fields in (entry.get("variantes") or {}).items():
                values.update({f"{variant}_{field}": value for field, value in fields.items()})
            continue
        prefix = TYPE_PREFIXES.get(type_name)
        if prefix is None:                      # type inconnu (preset plus récent) : ignoré, rien ne casse
            continue
        for fields in (entry.get("variantes") or {}).values():
            values.update({f"{prefix}{field}": value for field, value in fields.items()})
    return values


def preset_path(name: str, folder: Path | None = None) -> Path:
    """Fichier d'un preset : son nom, sans les caractères interdits par Windows."""
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "preset"
    return (folder or PRESETS_DIR) / f"{safe}.json"


def save_preset(preset: dict[str, Any], folder: Path | None = None) -> Path:
    """Écrit un preset (fichier temporaire puis remplacement : jamais un fichier à moitié écrit, le dossier est
    synchronisé dans le cloud)."""
    path = preset_path(preset["nom"], folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(preset, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_preset(path: Path) -> dict[str, Any]:
    """Lit un preset ; un format plus récent que `FORMAT` est refusé (ValueError) plutôt que mal lu."""
    preset = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(preset.get("format", 0)) > FORMAT:
        raise ValueError(f"{path.name} : format {preset.get('format')} plus récent que {FORMAT}")
    return preset


def list_presets(folder: Path | None = None) -> dict[str, Path]:
    """Presets du dossier : {nom: fichier}, triés par nom."""
    found: dict[str, Path] = {}
    for path in sorted((folder or PRESETS_DIR).glob("*.json")):
        try:
            found[load_preset(path)["nom"]] = path
        except (OSError, ValueError, KeyError):
            continue
    return dict(sorted(found.items(), key=lambda item: item[0].lower()))


def convert_presets(source: Path, folder: Path | None = None) -> list[Path]:
    """Convertisseur : chaque preset de l'appli (`pipeline_settings.presets.json` : {nom: réglages à plat})
    devient un preset fm_theme. La source n'est pas modifiée."""
    presets = json.loads(Path(source).read_text(encoding="utf-8"))
    return [save_preset(from_settings(values, name), folder) for name, values in presets.items()]


if __name__ == "__main__":     # python -m fm_theme.presets <pipeline_settings.presets.json>
    import sys
    for written in convert_presets(Path(sys.argv[1])):
        print(written)
