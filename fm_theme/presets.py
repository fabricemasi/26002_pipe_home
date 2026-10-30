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
# `row_templates` : gabarits des lignes des fenetres de reglages, un par type de ligne (fm_theme.cells,
# ROW_TEMPLATES_KEY) — de l'aspect commun a toutes les applis du theme (choix de l'utilisateur, 2026-10-29).
GENERAL_KEYS = ("colors", "ui_scale", "window_radius", "row_templates")
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


def to_settings(preset: dict[str, Any], variants: dict | None = None) -> dict[str, Any]:
    """Réglages à plat d'un preset fm_theme (inverse exact de `from_settings`). `variants` : {type: variante} que
    l'appli UTILISE à la place de la variante par défaut (sa surcharge, `theme_default_variants` ; alias compris,
    une variante inconnue retombe sur la variante par défaut)."""
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
        # Une seule variante à plat : celle PAR DÉFAUT du type (les autres attendent qu'un élément les choisisse).
        values.update({f"{prefix}{field}": value
                       for field, value in variant_fields(entry, used_variant(entry, (variants or {}).get(type_name))).items()})
    return values


def used_variant(entry: dict, wanted: str | None = None) -> str:
    """Variante réellement utilisée d'un type : `wanted` (ou la variante dont c'est un ancien nom) si elle existe,
    sinon la variante par défaut. Ordre de résolution du plan : variante nommée par l'élément / surcharge de
    l'appli -> défaut du preset -> première variante."""
    variants = entry.get("variantes") or {}
    if wanted:
        wanted = wanted if wanted in variants else (entry.get("alias") or {}).get(wanted)
        if wanted in variants:
            return wanted
    return default_variant(entry)


def used_variants(preset: dict, wanted: dict | None = None) -> dict[str, str]:
    """{type: variante utilisée} pour tous les types à variantes du preset."""
    return {type_name: used_variant(entry, (wanted or {}).get(type_name))
            for type_name, entry in (preset.get("types") or {}).items() if type_name in TYPE_PREFIXES}


def default_variant(entry: dict) -> str:
    """Variante par défaut d'un type (repli : « standard », puis la première)."""
    variants = entry.get("variantes") or {}
    for name in (entry.get("defaut"), STANDARD):
        if name in variants:
            return name
    return next(iter(variants), STANDARD)


def variant_fields(entry: dict, variant: str | None = None) -> dict:
    """Champs (sans préfixe) d'une variante d'un type (par défaut : sa variante par défaut)."""
    return dict((entry.get("variantes") or {}).get(variant or default_variant(entry)) or {})


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


# -- Gestion (éditeur fm_theme) : un renommage garde l'ancien nom en alias (`alias`), qu'une appli liée à
# l'ancien nom retrouve (`find_preset`) : choisir un preset dans une appli ne doit jamais se casser.

def find_preset(name: str, folder: Path | None = None) -> Path | None:
    """Fichier du preset `name`, ou de celui qui porte `name` en alias (renommé) ; None s'il n'existe pas."""
    if not name:
        return None
    path = preset_path(name, folder)
    if path.is_file():
        return path
    for candidate in sorted((folder or PRESETS_DIR).glob("*.json")):
        try:
            if name in (load_preset(candidate).get("alias") or ()):
                return candidate
        except (OSError, ValueError):
            continue
    return None


def unique_name(base: str, folder: Path | None = None) -> str:
    """`base`, ou `base 2`, `base 3`... : un nom de preset libre (nom ou alias)."""
    base = (base or "Preset").strip() or "Preset"
    name, n = base, 2
    while find_preset(name, folder) is not None:
        name, n = f"{base} {n}", n + 1
    return name


_DROP = object()


def _set_value(preset: dict, key: str, value, editing: dict) -> None:
    """Range une clé à plat dans le preset (`_DROP` : la retire) ; un type à variantes la range dans la variante
    `editing[type]` (sinon sa variante par défaut)."""
    where = theme_key(key)
    if where is None:
        return
    type_name, variant, field = where
    if type_name == "general":
        target = preset.setdefault("general", {})
    else:
        entry = preset.setdefault("types", {}).setdefault(
            type_name, {"defaut": None if type_name == "toggle" else STANDARD, "variantes": {}})
        if not variant:                                   # clé propre au type (toggle_style...)
            target = entry
        else:
            if type_name != "toggle":
                variant = editing.get(type_name) or default_variant(entry)
            target = entry.setdefault("variantes", {}).setdefault(variant, {})
    if value is _DROP:
        target.pop(field, None)
    else:
        target[field] = value


def update_preset(name: str, changes: dict, drop: tuple = (), folder: Path | None = None,
                  editing: dict | None = None) -> dict:
    """Modifie les valeurs d'aspect du preset `name` (clés à plat ; les autres sont ignorées) SANS toucher aux
    autres variantes : chaque type écrit dans la variante `editing[type]`, sinon dans sa variante par défaut."""
    preset = load_preset(find_preset(name, folder))
    for key, value in changes.items():
        _set_value(preset, key, value, editing or {})
    for key in drop:
        _set_value(preset, key, _DROP, editing or {})
    save_preset(preset, folder)
    return preset


def save_row_templates(name: str, templates: dict, folder: Path | None = None) -> bool:
    """Gabarits des lignes des fenêtres de réglages dans le preset `name` (valeur générale `row_templates`).
    N'écrit que s'ils ont changé (chaque écriture réveille la surveillance du fichier dans les applis). Retourne
    True si le fichier a été écrit ; preset introuvable : rien."""
    try:
        preset = load_preset(find_preset(name, folder))
    except (OSError, ValueError, TypeError):
        return False
    if (preset.get("general") or {}).get("row_templates") == templates:
        return False
    update_preset(name, {"row_templates": templates}, folder=folder)
    return True


# -- Variantes d'un type (titres, curseurs, champs, boutons, tableaux, onglets, menus, fenêtres) : créées,
# dupliquées, renommées (l'ancien nom reste en alias), supprimées, choisies par défaut. Les toggles gardent
# leurs propres styles (toggle1, toggle2... : `toggle_styles`, menu des styles de la fenêtre de réglages).

def _type_entry(preset: dict, type_name: str) -> dict:
    if type_name not in TYPE_PREFIXES:
        raise ValueError(f"type sans variantes gérées ici : {type_name}")
    entry = preset.setdefault("types", {}).setdefault(type_name, {"defaut": STANDARD, "variantes": {}})
    if not entry.setdefault("variantes", {}):
        entry["variantes"][STANDARD] = {}
    return entry


def variant_names(preset: dict, type_name: str) -> list[str]:
    return list(_type_entry(preset, type_name)["variantes"])


def type_flat(preset: dict, type_name: str, variant: str | None = None) -> dict:
    """Clés à plat (avec préfixe) d'une variante d'un type : ce que l'éditeur affiche quand on l'édite."""
    prefix = TYPE_PREFIXES[type_name]
    return {f"{prefix}{f}": v for f, v in variant_fields(_type_entry(preset, type_name), variant).items()}


def resolve_variant(preset: dict, type_name: str, name: str) -> str:
    """Nom actuel d'une variante (son nom, ou un ancien nom gardé en alias)."""
    entry = _type_entry(preset, type_name)
    return name if name in entry["variantes"] else (entry.get("alias") or {}).get(name, name)


def _unique_variant(entry: dict, base: str) -> str:
    base = (base or "variante").strip() or "variante"
    name, n = base, 2
    while name in entry["variantes"] or name in (entry.get("alias") or {}):
        name, n = f"{base} {n}", n + 1
    return name


def _edit_variants(name: str, type_name: str, action, folder: Path | None = None):
    preset = load_preset(find_preset(name, folder))
    result = action(_type_entry(preset, type_name))
    save_preset(preset, folder)
    return result


def add_variant(name: str, type_name: str, new: str, source: str | None = None,
                folder: Path | None = None) -> str:
    """Nouvelle variante (copie de `source`, sinon de la variante par défaut). Retourne son nom (unique)."""
    def action(entry):
        variant = _unique_variant(entry, new)
        entry["variantes"][variant] = variant_fields(entry, source)
        return variant
    return _edit_variants(name, type_name, action, folder)


def rename_variant(name: str, type_name: str, old: str, new: str, folder: Path | None = None) -> str:
    """Renomme (nom unique) ; l'ancien nom devient un alias (les éléments qui le citent le retrouvent)."""
    def action(entry):
        new_name = (new or "").strip()
        if old not in entry["variantes"] or not new_name or new_name == old:
            return old
        new_name = _unique_variant(entry, new_name)
        entry["variantes"] = {(new_name if k == old else k): v for k, v in entry["variantes"].items()}
        alias = entry.setdefault("alias", {})
        alias.update({k: new_name for k, v in alias.items() if v == old})
        alias[old] = new_name
        if entry.get("defaut") == old:
            entry["defaut"] = new_name
        return new_name
    return _edit_variants(name, type_name, action, folder)


def delete_variant(name: str, type_name: str, variant: str, folder: Path | None = None) -> None:
    """Supprime une variante (jamais la dernière) ; si c'était la variante par défaut, la première la remplace."""
    def action(entry):
        if variant in entry["variantes"] and len(entry["variantes"]) > 1:
            del entry["variantes"][variant]
            if entry.get("defaut") == variant:
                entry["defaut"] = next(iter(entry["variantes"]))
    _edit_variants(name, type_name, action, folder)


def set_default_variant(name: str, type_name: str, variant: str, folder: Path | None = None) -> None:
    """Variante par défaut d'un type : c'est elle que les applis reçoivent à plat."""
    def action(entry):
        if variant in entry["variantes"]:
            entry["defaut"] = variant
    _edit_variants(name, type_name, action, folder)


def new_preset(name: str, values: dict, folder: Path | None = None) -> str:
    """Nouveau preset (nom rendu unique) à partir de réglages à plat. Retourne son nom."""
    name = unique_name(name, folder)
    save_preset(from_settings(values, name), folder)
    return name


def duplicate_preset(name: str, new: str | None = None, folder: Path | None = None) -> str:
    previous = load_preset(find_preset(name, folder))
    return new_preset(new or f"{previous['nom']} copie", to_settings(previous), folder)


def rename_preset(old: str, new: str, folder: Path | None = None) -> str:
    """Renomme (nom rendu unique) ; l'ancien nom devient un alias. Retourne le nom retenu."""
    path = find_preset(old, folder)
    previous = load_preset(path)
    new = (new or "").strip()
    if not new or new == previous["nom"]:
        return previous["nom"]
    new = unique_name(new, folder)
    preset = dict(previous, nom=new)
    preset["alias"] = sorted(set(previous.get("alias") or ()) | {previous["nom"]})
    save_preset(preset, folder)
    path.unlink()
    return new


def delete_preset(name: str, folder: Path | None = None) -> None:
    path = find_preset(name, folder)
    if path is not None:
        path.unlink()


def convert_presets(source: Path, folder: Path | None = None) -> list[Path]:
    """Convertisseur : chaque preset de l'appli (`pipeline_settings.presets.json` : {nom: réglages à plat})
    devient un preset fm_theme. La source n'est pas modifiée."""
    presets = json.loads(Path(source).read_text(encoding="utf-8"))
    return [save_preset(from_settings(values, name), folder) for name, values in presets.items()]


if __name__ == "__main__":     # python -m fm_theme.presets <pipeline_settings.presets.json>
    import sys
    for written in convert_presets(Path(sys.argv[1])):
        print(written)
