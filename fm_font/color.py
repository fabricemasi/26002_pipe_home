"""Polices couleur COLR v0 / v1 et CPAL (sans Qt) : palettes et calques de couleur d'un glyphe, rangés dans la lib
de l'UFO aux clés lues par ufo2ft (qui compile les tables COLR et CPAL). Un calque = un glyphe ordinaire (dessiné
comme les autres) + une PEINTURE : un indice de la palette (aplat, COLR v0) ou un DÉGRADÉ (COLR v1) linéaire ou
radial entre deux couleurs de la palette.

Saisie texte (panneaux) : palette = « #ff0000 #00a0ff80 » ; calques = « A.rouge:0, A.bleu:lin(0,1), A.o:rad(2,0) »
(`lin(a,b[,angle])` : de la couleur a à la couleur b, angle en degrés, 90 = de bas en haut ; `rad(a,b)` : du centre
vers le bord).

Dégradés : la description (`GRADIENTS_KEY`, propre au module) est la référence ; la peinture COLR v1 écrite dans
`LAYERS_KEY` (lisible par ufo2ft / fontmake) est RECALCULÉE à la compilation (`refreshed_layers`) depuis la boîte
du glyphe calque : modifier le dessin ne laisse jamais un dégradé décalé."""
from __future__ import annotations

import math
import re

PALETTES_KEY = "com.github.googlei18n.ufo2ft.colorPalettes"
LAYERS_KEY = "com.github.googlei18n.ufo2ft.colorLayers"
GRADIENTS_KEY = "fm_font.colorLayers"               # {glyphe: [[calque, peinture]]} quand un calque a un dégradé
PAINT_COLR_LAYERS, PAINT_SOLID, PAINT_LINEAR, PAINT_RADIAL, PAINT_GLYPH = 1, 2, 4, 6, 10   # ot.PaintFormat
_GRADIENT = re.compile(r"^(lin|rad)\(\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(-?[\d.]+)\s*)?\)$")


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


def layers(font, name: str) -> list[tuple[str, object]]:
    """[(calque, peinture)] ; peinture = indice (aplat) ou (« lin » | « rad », couleur a, couleur b, angle)."""
    gradients = (font.lib.get(GRADIENTS_KEY) or {}).get(name)
    if gradients is not None:
        return [(g, tuple(p) if isinstance(p, list) else int(p)) for g, p in gradients]
    value = (font.lib.get(LAYERS_KEY) or {}).get(name, [])
    return [(g, int(i)) for g, i in value] if isinstance(value, list) else []


def _format_paint(paint) -> str:
    if isinstance(paint, tuple):
        kind, a, b, angle = paint
        return f"{kind}({a},{b})" if kind == "rad" or angle == 90 else f"{kind}({a},{b},{angle:g})"
    return str(paint)


def format_layers(pairs) -> str:
    return ", ".join(f"{g}:{_format_paint(p)}" for g, p in pairs)


def _parse_paint(part: str, text: str):
    match = _GRADIENT.match(text.replace(" ", ""))
    if match:
        kind, a, b, angle = match.groups()
        return (kind, int(a), int(b), float(angle) if angle is not None else 90.0)
    try:
        return int(text)
    except ValueError:
        raise ColorError(f"Calque « {part} » : indice de couleur, lin(a,b[,angle]) ou rad(a,b).") from None


def parse_layers(text: str) -> list[tuple[str, object]]:
    pairs = []
    for part in re.split(r",(?![^(]*\))", text):             # virgules hors des parenthèses
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ColorError(f"Calque « {part} » : glyphe:peinture attendu (ex. A.rouge:0, A.bleu:lin(0,1)).")
        glyph, paint = part.rsplit(":", 1)
        pairs.append((glyph.strip(), _parse_paint(part, paint.strip())))
    return pairs


def _indexes(paint) -> list[int]:
    return [paint[1], paint[2]] if isinstance(paint, tuple) else [paint]


def _bounds(font, name):
    from fontTools.pens.boundsPen import BoundsPen
    pen = BoundsPen(font)
    font[name].draw(pen)
    return pen.bounds or (0, 0, font[name].width or 0, 0)


def gradient_geometry(bounds, paint) -> dict:
    """Géométrie d'un dégradé sur la boîte `bounds` : linéaire (p0, p1, p2) ou radial (centre, r1)."""
    kind, _a, _b, angle = paint
    x0, y0, x1, y1 = bounds
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if kind == "lin":
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        half = abs((x1 - x0) / 2 * dx) + abs((y1 - y0) / 2 * dy) or 1.0         # la boîte entière est couverte
        p0 = (round(cx - dx * half), round(cy - dy * half))
        p1 = (round(cx + dx * half), round(cy + dy * half))
        p2 = (round(p0[0] - dy * half), round(p0[1] + dx * half))            # perpendiculaire : dégradé « droit »
        return {"x0": p0[0], "y0": p0[1], "x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1]}
    radius = round(math.hypot(x1 - x0, y1 - y0) / 2) or 1
    return {"x0": round(cx), "y0": round(cy), "r0": 0, "x1": round(cx), "y1": round(cy), "r1": radius}


def _paint_dict(font, layer: str, paint) -> dict:
    if not isinstance(paint, tuple):
        inner = {"Format": PAINT_SOLID, "PaletteIndex": int(paint), "Alpha": 1.0}
    else:
        kind, a, b, _angle = paint
        stops = {"Extend": "pad", "ColorStop": [{"StopOffset": 0.0, "PaletteIndex": int(a), "Alpha": 1.0},
                                               {"StopOffset": 1.0, "PaletteIndex": int(b), "Alpha": 1.0}]}
        inner = {"Format": PAINT_LINEAR if kind == "lin" else PAINT_RADIAL, "ColorLine": stops,
                 **gradient_geometry(_bounds(font, layer), paint)}
    return {"Format": PAINT_GLYPH, "Glyph": layer, "Paint": inner}


def colr_value(font, pairs):
    """Valeur de `LAYERS_KEY` pour un glyphe : liste v0 si tout est en aplats, sinon peinture COLR v1."""
    if not any(isinstance(p, tuple) for _g, p in pairs):
        return [[g, int(p)] for g, p in pairs]
    return {"Format": PAINT_COLR_LAYERS, "Layers": [_paint_dict(font, g, p) for g, p in pairs]}


def refreshed_layers(font):
    """`LAYERS_KEY` recalculé pour la compilation (dégradés suivant le dessin actuel), ou None sans dégradé."""
    gradients = font.lib.get(GRADIENTS_KEY)
    if not gradients:
        return None
    value = dict(font.lib.get(LAYERS_KEY) or {})
    for name, pairs in gradients.items():
        if name in font and all(g in font for g, _p in pairs):
            value[name] = colr_value(font, [(g, tuple(p) if isinstance(p, list) else p) for g, p in pairs])
    return value


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
    """Calques de couleur de `name` (vérifiés : glyphes existants, indices dans la palette), un pas d'annulation.
    Avec un dégradé : description dans `GRADIENTS_KEY` + peinture COLR v1 dans `LAYERS_KEY`."""
    font = project.font
    count = len(palette(font))
    for glyph, paint in pairs:
        if glyph not in font:
            raise ColorError(f"Calque : le glyphe « {glyph} » n'existe pas.")
        for index in _indexes(paint):
            if not 0 <= index < count and index != 0xFFFF:
                raise ColorError(f"Calque {glyph} : couleur {index} hors de la palette ({count} couleur(s)).")
        if glyph == name:
            raise ColorError("Un glyphe ne peut pas être son propre calque.")
    gradient = any(isinstance(p, tuple) for _g, p in pairs)
    before = [(dict(m.font.lib.get(LAYERS_KEY) or {}), dict(m.font.lib.get(GRADIENTS_KEY) or {}))
              for m in project.masters]

    def apply(states):
        for m, (mapping, gradients) in zip(project.masters, states):
            for key, value in ((LAYERS_KEY, mapping), (GRADIENTS_KEY, gradients)):
                if value:
                    m.font.lib[key] = value
                else:
                    m.font.lib.pop(key, None)
        project.notify("glyph", (0, name))
    after = []
    for m, (mapping, gradients) in zip(project.masters, before):
        mapping, gradients = dict(mapping), dict(gradients)
        mapping.pop(name, None)
        gradients.pop(name, None)
        if pairs:
            mapping[name] = colr_value(m.font, pairs)
            if gradient:
                gradients[name] = [[g, list(p) if isinstance(p, tuple) else p] for g, p in pairs]
        after.append((mapping, gradients))
    apply(after)
    project.undo.push(f"Calques couleur de {name}", lambda: apply(before), lambda: apply(after))


class compile_layers:
    """`with compile_layers(*fonts):` : peintures COLR v1 recalculées pendant la compilation, lib remise après."""

    def __init__(self, *fonts):
        self.fonts = fonts
        self.saved = []

    def __enter__(self):
        for font in self.fonts:
            value = refreshed_layers(font)
            if value is not None:
                self.saved.append((font, font.lib.get(LAYERS_KEY)))
                font.lib[LAYERS_KEY] = value
        return self

    def __exit__(self, *exc):
        for font, value in self.saved:
            if value is None:
                font.lib.pop(LAYERS_KEY, None)
            else:
                font.lib[LAYERS_KEY] = value
        return False
