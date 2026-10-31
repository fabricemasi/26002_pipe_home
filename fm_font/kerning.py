"""Crénage (sans Qt) : paires, classes (groupes UFO `public.kern1.*` / `public.kern2.*`), exceptions, recherche de
la valeur effective, aide automatique contrôlable (suggestions, jamais appliquées sans l'utilisateur).

Priorité UFO : glyphe-glyphe > glyphe-classe > classe-glyphe > classe-classe. Une EXCEPTION est une paire au
niveau du glyphe alors qu'une paire de classes existe."""
from __future__ import annotations

from . import contours as C

KERN1, KERN2 = "public.kern1.", "public.kern2."


def group_of(font, glyph: str, side: int) -> str | None:
    prefix = KERN1 if side == 1 else KERN2
    for name, members in font.groups.items():
        if name.startswith(prefix) and glyph in members:
            return name
    return None


def group_index(font) -> tuple[dict, dict]:
    """{glyphe: classe} pour chaque côté (à construire une fois par mise en page, pas par paire)."""
    left, right = {}, {}
    for name, members in font.groups.items():
        if name.startswith(KERN1):
            for g in members:
                left[g] = name
        elif name.startswith(KERN2):
            for g in members:
                right[g] = name
    return left, right


def lookup(font, left: str, right: str, index=None) -> tuple[float, tuple | None]:
    """(valeur, paire qui la donne) ; (0, None) sans crénage."""
    kerning = font.kerning
    li, ri = index or group_index(font)
    lg, rg = li.get(left), ri.get(right)
    for pair in ((left, right), (left, rg), (lg, right), (lg, rg)):
        if None not in pair and pair in kerning:
            return kerning[pair], pair
    return 0, None


def is_exception(font, pair, index=None) -> bool:
    left, right = pair
    if left.startswith(KERN1) and right.startswith(KERN2):
        return False
    li, ri = index or group_index(font)
    lg, rg = li.get(left, left), ri.get(right, right)
    return (lg, rg) != (left, right) and any(p in font.kerning for p in ((lg, rg), (left, rg), (lg, right))
                                              if p != (left, right))


def target_pair(font, left: str, right: str, exception: bool = False, index=None) -> tuple:
    """Paire où écrire une valeur : celle des classes (si elles existent), sauf exception demandée."""
    if exception:
        return (left, right)
    li, ri = index or group_index(font)
    return (li.get(left, left), ri.get(right, right))


def set_value(project, master: int, pair: tuple, value: float | None, label: str = "Crénage") -> None:
    """Écrit (ou retire si None) une valeur de paire, un pas d'annulation."""
    kerning = project.masters[master].font.kerning
    before = kerning.get(pair)
    if before == value:
        return

    def apply(v):
        if v is None:
            kerning.pop(pair, None)
        else:
            kerning[pair] = v
        project.notify("kerning", pair)
    apply(value)
    project.undo.push(label, lambda: apply(before), lambda: apply(value))


def set_group(project, side: int, name: str, members, all_masters: bool = True) -> None:
    """Crée / remplace une classe de crénage ; un glyphe quitte son ancienne classe du même côté (règle UFO)."""
    prefix = KERN1 if side == 1 else KERN2
    key = name if name.startswith(prefix) else prefix + name
    members = list(dict.fromkeys(members))
    targets = range(len(project.masters)) if all_masters else (0,)
    before = [{k: list(v) for k, v in project.masters[i].font.groups.items()} for i in targets]

    def do():
        for i in targets:
            groups = project.masters[i].font.groups
            for other, glyphs in list(groups.items()):
                if other != key and other.startswith(prefix) and set(glyphs) & set(members):
                    groups[other] = [g for g in glyphs if g not in members]
            if members:
                groups[key] = list(members)
            else:
                groups.pop(key, None)
        project.notify("kerning", None)

    def undo():
        for k, i in enumerate(targets):
            groups = project.masters[i].font.groups
            groups.clear()
            groups.update({n: list(v) for n, v in before[k].items()})
        project.notify("kerning", None)
    do()
    project.undo.push(f"Classe {key[len(prefix):]}", undo, do)


# -- aide automatique --

def profile(glyph, font, bands: int = 24, layer=None) -> tuple[list, list, float, float]:
    """Profils gauche / droit : pour chaque bande horizontale, x minimal et maximal de l'encre (None si vide)."""
    info = font.info
    bottom = info.descender if info.descender is not None else -200
    top = info.ascender if info.ascender is not None else 800
    polys = []
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    pen = DecomposingRecordingPen(layer if layer is not None else font)
    glyph.draw(pen)
    for poly in _record_polys(pen.value):
        polys.append(poly)
    lefts, rights = [None] * bands, [None] * bands
    step = (top - bottom) / bands
    for b in range(bands):
        y = bottom + step * (b + 0.5)
        xs = []
        for poly in polys:
            for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
                if (y0 > y) != (y1 > y):
                    xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
        if xs:
            lefts[b], rights[b] = min(xs), max(xs)
    return lefts, rights, bottom, top


def _record_polys(value):
    out, cur = [], []
    for op, args in value:
        if op == "moveTo":
            cur = [args[0]]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "curveTo":
            pts = [cur[-1], *args]
            cur.extend(C.cubic_at(*pts, k / 8) for k in range(1, 9))
        elif op == "qCurveTo":
            start = cur[-1]
            for quad in C.quad_segments([start, *args]):
                cur.extend(C.quad_at(*quad, k / 8) for k in range(1, 9))
        elif op in ("closePath", "endPath"):
            if len(cur) > 2:
                out.append(cur)
            cur = []
    return out


def gap(left_glyph, right_glyph, font, depth: float = 0.15, cache: dict | None = None) -> float | None:
    """Espace optique entre deux glyphes posés côte à côte (sans crénage) : moyenne des distances des bandes, les
    creux limités à `depth` x hauteur (une ouverture comme celle du « c » ne compte qu'en partie)."""
    def prof(glyph):
        if cache is not None and glyph.name in cache:
            return cache[glyph.name]
        value = profile(glyph, font)
        if cache is not None:
            cache[glyph.name] = value
        return value
    _l1, r1, bottom, top = prof(left_glyph)
    l2, _r2, _b, _t = prof(right_glyph)
    limit = (top - bottom) * depth
    distances = []
    for a, b in zip(r1, l2):
        if a is None or b is None:
            continue
        distances.append(min(left_glyph.width - a + b, limit))
    if not distances:
        return None
    return sum(distances) / len(distances)


def suggest(font, pairs, reference=("n", "n"), strength: float = 1.0, threshold: float = 5,
            maximum: float = 200) -> dict:
    """Suggestions {paire: valeur} pour que l'espace optique de chaque paire rejoigne celui de la paire de
    référence. Contrôles : `strength` (0..1), `threshold` (valeurs plus petites ignorées), `maximum` (valeur
    absolue maximale). Ne modifie rien."""
    cache: dict = {}
    if reference[0] not in font or reference[1] not in font:
        return {}
    target = gap(font[reference[0]], font[reference[1]], font, cache=cache)
    if target is None:
        return {}
    out = {}
    for left, right in pairs:
        if left not in font or right not in font:
            continue
        value = gap(font[left], font[right], font, cache=cache)
        if value is None:
            continue
        kern = round((target - value) * strength)
        kern = max(-maximum, min(maximum, kern))
        if abs(kern) >= threshold:
            out[(left, right)] = kern
    return out
