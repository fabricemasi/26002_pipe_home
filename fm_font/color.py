"""Polices couleur COLR v0 / CPAL (sans Qt) : palettes et calques de couleur d'un glyphe, rangés dans la lib de
l'UFO aux clés lues par ufo2ft (qui compile les tables COLR et CPAL). Un calque = un glyphe ordinaire (dessiné
comme les autres) + un indice de couleur dans la palette.

Saisie texte (panneaux) : palette = « #ff0000 #00a0ff80 » ; calques = « A.rouge:0, A.bleu:1 »."""
from __future__ import annotations

PALETTES_KEY = "com.github.googlei18n.ufo2ft.colorPalettes"
LAYERS_KEY = "com.github.googlei18n.ufo2ft.colorLayers"


class ColorError(ValueError):
    pass


def _hex_to_rgba(text: str) -> tuple:
    t = text.strip().lstrip("#")
    if len(t) not in (6, 8) or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise ColorError(f"Couleur « {text} » : #rrggbb ou #rrggbbaa attendu.")
    values = [int(t[i:i + 2], 16) / 255 for i in range(0, len(t), 2)]
    if len(values) == 3:
        values.append(1.0)
    return tuple(round(v, 4) for v in values)


def _rgba_to_hex(rgba) -> str:
    r, g, b, a = (round(float(v) * 255) for v in rgba)
    return f"#{r:02x}{g:02x}{b:02x}" + ("" if a == 255 else f"{a:02x}")


def palette(font) -> list[str]:
    palettes = font.lib.get(PALETTES_KEY) or []
    return [_rgba_to_hex(c) for c in palettes[0]] if palettes else []


def parse_palette(text: str) -> list[tuple]:
    return [_hex_to_rgba(part) for part in text.replace(",", " ").split()]


def layers(font, name: str) -> list[tuple[str, int]]:
    return [(g, int(i)) for g, i in (font.lib.get(LAYERS_KEY) or {}).get(name, [])]


def format_layers(pairs) -> str:
    return ", ".join(f"{g}:{i}" for g, i in pairs)


def parse_layers(text: str) -> list[tuple[str, int]]:
    pairs = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ColorError(f"Calque « {part} » : glyphe:indice attendu (ex. A.rouge:0).")
        glyph, index = part.rsplit(":", 1)
        try:
            pairs.append((glyph.strip(), int(index)))
        except ValueError as exc:
            raise ColorError(f"Calque « {part} » : l'indice de couleur est un nombre.") from exc
    return pairs


def set_palette(project, colors: list[tuple]) -> None:
    """Palette 0 (tous les masters), un pas d'annulation. Liste vide = plus de couleur."""
    before = [m.font.lib.get(PALETTES_KEY) for m in project.masters]
    after = [[list(c) for c in colors]] if colors else None

    def apply(values):
        for m, v in zip(project.masters, values):
            if v is None:
                m.font.lib.pop(PALETTES_KEY, None)
            else:
                m.font.lib[PALETTES_KEY] = v
        project.notify("info", PALETTES_KEY)
    apply([after] * len(project.masters))
    project.undo.push("Palette couleur", lambda: apply(before), lambda: apply([after] * len(project.masters)))


def set_layers(project, name: str, pairs) -> None:
    """Calques de couleur de `name` (vérifiés : glyphes existants, indices dans la palette), un pas d'annulation."""
    font = project.font
    count = len(palette(font))
    for glyph, index in pairs:
        if glyph not in font:
            raise ColorError(f"Calque : le glyphe « {glyph} » n'existe pas.")
        if not 0 <= index < count and index != 0xFFFF:
            raise ColorError(f"Calque {glyph} : couleur {index} hors de la palette ({count} couleur(s)).")
        if glyph == name:
            raise ColorError("Un glyphe ne peut pas être son propre calque.")
    before = [dict(m.font.lib.get(LAYERS_KEY) or {}) for m in project.masters]

    def apply(maps):
        for m, mapping in zip(project.masters, maps):
            if mapping:
                m.font.lib[LAYERS_KEY] = mapping
            else:
                m.font.lib.pop(LAYERS_KEY, None)
        project.notify("glyph", (0, name))
    after = []
    for mapping in before:
        new = dict(mapping)
        if pairs:
            new[name] = [[g, i] for g, i in pairs]
        else:
            new.pop(name, None)
        after.append(new)
    apply(after)
    project.undo.push(f"Calques couleur de {name}", lambda: apply(before), lambda: apply(after))
