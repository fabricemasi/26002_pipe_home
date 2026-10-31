"""Masters et interpolation (sans Qt) : compatibilité des contours, interpolation d'un glyphe ou d'une instance
entière par le modèle de variation de fontTools (le même que celui de la police variable compilée).

JAMAIS de résultat faux silencieux : un glyphe incompatible lève `InterpolationError` avec la raison précise
(nombre de contours, de points, types de segments, composants, ancres)."""
from __future__ import annotations

from fontTools.varLib.models import VariationModel, normalizeLocation

from .undo import glyph_restore, glyph_snapshot  # noqa: F401 - glyph_snapshot réexporté pour les appelants


class InterpolationError(ValueError):
    pass


def glyph_signature(glyph) -> tuple:
    return (tuple(tuple(p.type for p in c) for c in glyph.contours),
            tuple(c.baseGlyph for c in glyph.components),
            tuple(sorted(a.name or "" for a in glyph.anchors)))


def glyph_problem(glyphs, names) -> str | None:
    """Première différence entre les versions d'un glyphe dans les masters, None si compatibles."""
    ref = glyphs[0]
    for glyph, master in zip(glyphs[1:], names[1:]):
        if len(glyph.contours) != len(ref.contours):
            return f"{ref.name} : {len(ref.contours)} contours dans « {names[0]} », {len(glyph.contours)} dans « {master} »"
        for k, (a, b) in enumerate(zip(ref.contours, glyph.contours)):
            if len(a) != len(b):
                return f"{ref.name}, contour {k + 1} : {len(a)} points dans « {names[0]} », {len(b)} dans « {master} »"
            for i, (p, q) in enumerate(zip(a, b)):
                if p.type != q.type:
                    return (f"{ref.name}, contour {k + 1}, point {i + 1} : type {p.type or 'poignée'} / "
                            f"{q.type or 'poignée'} (« {master} »)")
        if [c.baseGlyph for c in ref.components] != [c.baseGlyph for c in glyph.components]:
            return f"{ref.name} : composants différents dans « {master} »"
        if sorted(a.name or "" for a in ref.anchors) != sorted(a.name or "" for a in glyph.anchors):
            return f"{ref.name} : ancres différentes dans « {master} »"
    return None


def incompatibilities(project) -> list[str]:
    if len(project.masters) < 2:
        return []
    names = [m.name for m in project.masters]
    problems = []
    for glyph in project.masters[0].font:
        missing = [m.name for m in project.masters[1:] if glyph.name not in m.font]
        if missing:
            problems.append(f"{glyph.name} : absent de « {missing[0]} »")
            continue
        problem = glyph_problem([m.font[glyph.name] for m in project.masters], names)
        if problem:
            problems.append(problem)
    return problems


def _model(project):
    axes = {a.name: (a.minimum, a.default, a.maximum) for a in project.axes}
    locations = [normalizeLocation({a: m.location.get(a, axes[a][1]) for a in axes}, axes) for m in project.masters]
    return VariationModel(locations, axisOrder=list(axes)), axes


def _flat(glyph) -> list[float]:
    values = [glyph.width]
    for c in glyph.contours:
        for p in c:
            values += [p.x, p.y]
    for comp in glyph.components:
        values += list(comp.transformation)
    for a in sorted(glyph.anchors, key=lambda a: a.name or ""):
        values += [a.x, a.y]
    return values


def interpolate_glyph(project, name: str, location: dict, target=None):
    """Glyphe interpolé à `location` (coordonnées de conception). `target` : glyphe à remplir (sinon une copie du
    glyphe du master par défaut). Lève InterpolationError si les masters sont incompatibles."""
    glyphs = []
    for m in project.masters:
        if name not in m.font:
            raise InterpolationError(f"{name} : absent de « {m.name} »")
        glyphs.append(m.font[name])
    problem = glyph_problem(glyphs, [m.name for m in project.masters])
    if problem:
        raise InterpolationError(problem)
    model, axes = _model(project)
    loc = normalizeLocation({a: location.get(a, axes[a][1]) for a in axes}, axes)
    master_values = [_flat(g) for g in glyphs]
    values = [model.interpolateFromMasters(loc, [mv[k] for mv in master_values]) for k in range(len(master_values[0]))]
    if target is None:
        import copy
        target = copy.deepcopy(glyphs[0])
    else:
        glyph_restore(target, glyph_snapshot(glyphs[0]))
    it = iter(values)
    target.width = next(it)
    for c in target.contours:
        for p in c:
            p.x, p.y = next(it), next(it)
    for comp in target.components:
        from fontTools.misc.transform import Transform
        comp.transformation = Transform(*(next(it) for _ in range(6)))
    for a in sorted(target.anchors, key=lambda a: a.name or ""):
        a.x, a.y = next(it), next(it)
    return target


def instance_font(project, location: dict, style_name: str = "Instance"):
    """UFO complet interpolé (glyphes, crénage, métriques verticales). Erreur si un glyphe est incompatible."""
    import copy
    from .kerning import group_index, lookup
    base = project.masters[0].font
    font = copy.deepcopy(base)
    font.info.styleName = style_name
    for glyph in font:
        interpolate_glyph(project, glyph.name, location, target=glyph)
    model, axes = _model(project)
    loc = normalizeLocation({a: location.get(a, axes[a][1]) for a in axes}, axes)
    pairs = set()
    for m in project.masters:
        pairs |= set(m.font.kerning)
    font.kerning.clear()
    for pair in pairs:
        per_master = []
        for m in project.masters:
            value = m.font.kerning.get(pair)
            if value is None:
                left, right = pair
                value = 0 if left.startswith("public.") or right.startswith("public.") else \
                    lookup(m.font, left, right, group_index(m.font))[0]
            per_master.append(value)
        value = round(model.interpolateFromMasters(loc, per_master))
        if value:
            font.kerning[pair] = value
    for attr in ("ascender", "descender", "capHeight", "xHeight"):
        values = [getattr(m.font.info, attr) for m in project.masters]
        if all(v is not None for v in values):
            setattr(font.info, attr, round(model.interpolateFromMasters(loc, values)))
    return font
