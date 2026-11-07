"""Réglages des toggles PAR ÉTAT (demande de l'utilisateur, 2026-10-30) : Toggles > <style> > État OFF / État ON,
chacun avec son FOND (largeur / hauteur, bordure, border radius, couleur) et sa COCHE (largeur / hauteur, bordure,
border radius, couleur, habillage : texte (police) ou icône (image importée), au milieu de la coche).

Clés : `<style>_<etat>_<partie>_<champ>` (ex. `toggle1_off_bg_width`, `toggle2_on_coche_text_font_size`).

Reprise des anciens réglages (un seul cadre et une seule coche pour les deux états : `<style>_outer_*`,
`<style>_coche_*`, fond `_outer_bg` / `_outer_bg_on`, hauteur de coche = hauteur du cadre - 2 x « distance du
bord ») : `fill_toggle_states(d)` ajoute à un dict de réglages les clés par état ABSENTES, déduites des anciennes
clés présentes dans CE dict (fichier, preset, thème : chaque couche séparément, avant leur fusion). Pur Python,
aucun import de l'appli.
"""
from __future__ import annotations

import re

STATES = ("off", "on")
SIDES = ("top", "right", "bottom", "left")
FONT_FIELDS = ("family", "bold", "italic", "size", "smoothing_enabled", "smoothing", "color")

# Valeurs par defaut d'un etat (sans prefixe). `coche_icon` : image importee dans data/toggle_icons/.
_BASE = {
    "bg_width": 29, "bg_height": 14,
    "bg_border_enabled": {s: True for s in SIDES}, "bg_border_enabled_linked": False,
    "bg_border": {s: "#2e343a" for s in SIDES}, "bg_border_thickness": 1,
    "bg_border_radius": 0, "bg_border_radius_linked": True,
    "bg_color": "#141618",
    "coche_width": 11, "coche_height": 12,
    "coche_border_enabled": {s: True for s in SIDES}, "coche_border_enabled_linked": False,
    "coche_border": {s: "#2e343a" for s in SIDES}, "coche_border_thickness": 1,
    "coche_border_radius": 0, "coche_border_radius_linked": True,
    "coche_color": "#3f6f9f",
    "coche_skin": "none", "coche_text": "",
    "coche_text_font_family": "", "coche_text_font_bold": True, "coche_text_font_italic": False,
    "coche_text_font_size": 10, "coche_text_font_smoothing_enabled": False, "coche_text_font_smoothing": "current",
    "coche_text_font_color": "#ffffff",
    "coche_icon": "",
}
FIELDS = tuple(_BASE)

# Anciennes cles (sans prefixe) qui declenchent la reprise.
_OLD = ("outer_width", "outer_height", "outer_border_enabled", "outer_border", "outer_border_thickness",
        "outer_border_radius", "outer_bg", "outer_bg_on", "coche_width", "coche_margin", "coche_border_enabled",
        "coche_border", "coche_border_thickness", "coche_border_radius", "coche_color", "coche_skin", "coche_text",
        "coche_icon", *(f"coche_text_font_{f}" for f in FONT_FIELDS))
_OLD_RE = re.compile(r"^(toggle\d+)_(" + "|".join(re.escape(k) for k in sorted(_OLD, key=len, reverse=True)) + r")$")


def defaults(prefix: str) -> dict:
    """Cles par etat d'un style, valeurs par defaut (Toggle 2 : cadre carre 22 x 22, coche en fondu invisible a
    l'etat OFF, comme avant)."""
    out = {}
    for state in STATES:
        values = dict(_BASE)
        if state == "on":
            values["bg_color"] = "#3f6f9f"
        if prefix == "toggle2":
            values.update(bg_width=22, bg_height=22, coche_width=11, coche_height=14)
            if state == "off":
                values.update(coche_color="#00000000", coche_border_enabled={s: False for s in SIDES})
        for field, value in values.items():
            out[f"{prefix}_{state}_{field}"] = _copy(value)
    return out


def _copy(value):
    return dict(value) if isinstance(value, dict) else value


def _from_old(old: dict, state: str, fade: bool) -> dict:
    """Champs d'un etat deduits des anciennes cles d'un style (`old` : {cle sans prefixe: valeur})."""
    g = old.get
    out = {}
    width, height = g("outer_width"), g("outer_height")
    if width is not None:
        out["bg_width"] = width
    if height is not None:
        out["bg_height"] = height
    for new, key in (("bg_border_enabled", "outer_border_enabled"), ("bg_border", "outer_border"),
                     ("bg_border_thickness", "outer_border_thickness"), ("bg_border_radius", "outer_border_radius")):
        if g(key) is not None:
            out[new] = _copy(g(key))
    bg = g("outer_bg_on") if state == "on" else g("outer_bg")
    if bg is not None:
        out["bg_color"] = bg
    if g("coche_width") is not None:
        out["coche_width"] = g("coche_width")
    if height is not None or g("coche_margin") is not None:
        h = int(height if height is not None else _BASE["bg_height"])
        margin = int(g("coche_margin") if g("coche_margin") is not None else 4)
        out["coche_height"] = max(2, h - 2 * margin)       # ancienne regle : hauteur du cadre - 2 x distance du bord
    for field in ("coche_border_enabled", "coche_border", "coche_border_thickness", "coche_border_radius",
                  "coche_color", "coche_skin", "coche_text", "coche_icon",
                  *(f"coche_text_font_{f}" for f in FONT_FIELDS)):
        if g(field) is not None:
            out[field] = _copy(g(field))
    if fade and state == "off":                             # fondu : la coche n'existait qu'a l'etat ON
        out.update(coche_color="#00000000", coche_border_enabled={s: False for s in SIDES}, coche_skin="none")
    return out


def fill_toggle_states(d: dict) -> dict:
    """Ajoute A `d` (sur place, et le rend) les cles par etat absentes, deduites des anciennes cles du meme style
    presentes dans `d`. Rien si `d` n'a pas d'anciennes cles, ou si les nouvelles y sont deja."""
    old: dict[str, dict] = {}
    for key, value in d.items():
        match = _OLD_RE.match(key)
        if match:
            old.setdefault(match[1], {})[match[2]] = value
    for prefix, values in old.items():
        fade = d.get(f"{prefix}_motion", "fade" if prefix == "toggle2" else "slide") == "fade"
        for state in STATES:
            for field, value in _from_old(values, state, fade).items():
                d.setdefault(f"{prefix}_{state}_{field}", value)
    return d


def state_values(settings: dict, prefix: str, state: str) -> dict:
    """{champ: valeur} d'un etat d'un style : la cle par etat de `settings`, sinon sa valeur par defaut."""
    base = defaults(prefix)
    return {field: settings.get(f"{prefix}_{state}_{field}", base[f"{prefix}_{state}_{field}"]) for field in FIELDS}
