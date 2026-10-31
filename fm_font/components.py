"""Composants et ancres (sans Qt) : ajout, décomposition, détection des cycles, construction automatique des
accentués à partir des ancres (é = e + aigu). La PROPAGATION est structurelle : un composé référence son glyphe
de base, toute modification de la base se voit dans le composé (le rendu suit les composants à la volée).

Ancres : la base porte `top` / `bottom` (…), la marque porte `_top` / `_bottom` ; une marque peut porter aussi
`top` pour empiler une seconde marque (mkmk). ufo2ft en tire les features mark / mkmk à la compilation."""
from __future__ import annotations

from fontTools.misc.transform import Transform
from fontTools.pens.transformPen import TransformPointPen
from ufoLib2.objects import Anchor, Component

from . import glyph_info

# Marque combinante -> noms de glyphes d'accent cherchés, dans l'ordre, et ancre utilisée.
MARKS = {
    0x0300: (("gravecomb", "grave"), "top"), 0x0301: (("acutecomb", "acute"), "top"),
    0x0302: (("circumflexcomb", "circumflex"), "top"), 0x0303: (("tildecomb", "tilde"), "top"),
    0x0304: (("macroncomb", "macron"), "top"), 0x0306: (("brevecomb", "breve"), "top"),
    0x0307: (("dotaccentcomb", "dotaccent"), "top"), 0x0308: (("dieresiscomb", "dieresis"), "top"),
    0x030A: (("ringcomb", "ring"), "top"), 0x030B: (("hungarumlautcomb", "hungarumlaut"), "top"),
    0x030C: (("caroncomb", "caron"), "top"), 0x0327: (("cedillacomb", "cedilla"), "bottom"),
    0x0328: (("ogonekcomb", "ogonek"), "bottom"), 0x0323: (("dotbelowcomb",), "bottom"),
}


class CycleError(ValueError):
    pass


def component_graph(font) -> dict[str, list[str]]:
    return {g.name: [c.baseGlyph for c in g.components] for g in font}


def find_cycles(font) -> list[list[str]]:
    """Cycles de composants (a -> b -> a) : bloquants à la compilation."""
    graph = component_graph(font)
    state: dict[str, int] = {}
    cycles = []

    def visit(name, stack):
        state[name] = 1
        stack.append(name)
        for base in graph.get(name, ()):
            if state.get(base) == 1:
                cycles.append(stack[stack.index(base):] + [base])
            elif base in graph and state.get(base) is None:
                visit(base, stack)
        stack.pop()
        state[name] = 2
    for name in graph:
        if state.get(name) is None:
            visit(name, [])
    return cycles


def would_cycle(font, glyph_name: str, base: str) -> bool:
    """Ajouter `base` comme composant de `glyph_name` créerait-il un cycle ?"""
    if base == glyph_name:
        return True
    graph = component_graph(font)
    todo, seen = [base], set()
    while todo:
        name = todo.pop()
        if name == glyph_name:
            return True
        if name in seen:
            continue
        seen.add(name)
        todo.extend(graph.get(name, ()))
    return False


def add_component(font, glyph, base: str, dx: float = 0, dy: float = 0) -> Component:
    if base not in font:
        raise ValueError(f"« {base} » n'existe pas.")
    if would_cycle(font, glyph.name, base):
        raise CycleError(f"« {base} » contient déjà « {glyph.name} » : cycle de composants.")
    comp = Component(base, Transform(1, 0, 0, 1, dx, dy))
    glyph.components.append(comp)
    return comp


def decompose(font, glyph, indexes=None) -> None:
    """Remplace les composants (tous ou `indexes`) par leurs contours, composants imbriqués compris."""
    indexes = range(len(glyph.components)) if indexes is None else indexes
    chosen = [glyph.components[i] for i in sorted(indexes)]
    pen = glyph.getPointPen()
    for comp in chosen:
        _draw_decomposed(font, comp.baseGlyph, Transform(*comp.transformation), pen, set())
    for comp in chosen:
        glyph.components.remove(comp)


def _draw_decomposed(font, name, matrix, pen, seen):
    if name in seen or name not in font:
        return
    base = font[name]
    tpen = TransformPointPen(pen, tuple(matrix))
    for contour in base.contours:
        contour.drawPoints(tpen)
    for comp in base.components:
        _draw_decomposed(font, comp.baseGlyph, matrix.transform(comp.transformation), pen, seen | {name})


def anchor(glyph, name: str):
    return next((a for a in glyph.anchors if a.name == name), None)


def set_anchor(glyph, name: str, x: float, y: float) -> Anchor:
    existing = anchor(glyph, name)
    if existing is not None:
        existing.x, existing.y = x, y
        return existing
    new = Anchor(x, y, name)
    glyph.anchors.append(new)
    return new


def mark_glyph_for(font, code: int, uppercase: bool) -> tuple[str | None, str]:
    names, where = MARKS.get(code, ((), "top"))
    for name in names:
        if uppercase and f"{name}.case" in font:
            return f"{name}.case", where
        if name in font:
            return name, where
    return None, where


def plan_composite(font, code: int) -> tuple[str, str, list[tuple[str, str]]] | None:
    """(nom du composé, base, [(marque, ancre)]) pour un caractère décomposable dont la base et les marques
    existent ; None sinon."""
    parts = glyph_info.decomposition(code)
    if len(parts) < 2:
        return None
    cmap = {c: g.name for g in font for c in g.unicodes}
    base = cmap.get(parts[0])
    if base is None:
        return None
    uppercase = chr(parts[0]).isupper()
    marks = []
    for mark_code in parts[1:]:
        mark, where = mark_glyph_for(font, mark_code, uppercase)
        if mark is None:
            return None
        marks.append((mark, where))
    return glyph_info.name_for_unicode(code), base, marks


def place_marks(font, glyph, base: str, marks) -> list[str]:
    """Pose base + marques en composants, alignés par ancres (sinon centrés au-dessus / au-dessous, avec un
    message). Renvoie les messages."""
    messages = []
    glyph.clearComponents()
    glyph.width = font[base].width
    add_component(font, glyph, base)
    attach = {}                                  # ancre courante par position (la marque posée la remplace)
    for a in font[base].anchors:
        attach[a.name] = (a.x, a.y)
    for mark, where in marks:
        mark_glyph = font[mark]
        mine = anchor(mark_glyph, f"_{where}")
        target = attach.get(where)
        if mine is not None and target is not None:
            dx, dy = target[0] - mine.x, target[1] - mine.y
        else:
            dx, dy = _fallback_offset(font, base, mark_glyph, where)
            messages.append(f"{glyph.name} : ancre « {where} » absente, {mark} centré.")
        add_component(font, glyph, mark, dx, dy)
        stacked = anchor(mark_glyph, where)
        if stacked is not None:
            attach[where] = (stacked.x + dx, stacked.y + dy)
    return messages


def _fallback_offset(font, base, mark_glyph, where):
    from .metrics import bounds
    b = bounds(font[base], font) or (0, 0, font[base].width, 0)
    m = bounds(mark_glyph, font) or (0, 0, mark_glyph.width, 0)
    dx = (b[0] + b[2]) / 2 - (m[0] + m[2]) / 2
    if where == "top":
        dy = b[3] + 40 - m[1]
    else:
        dy = b[1] - 40 - m[3]
    return dx, dy


def build_accented(project, codes) -> tuple[list[str], list[str]]:
    """Construit (tous les masters, un pas d'annulation) les accentués de `codes` dont la base et les marques
    existent ; un glyphe déjà DESSINÉ (contours) n'est pas remplacé. Renvoie (glyphes construits, messages)."""
    from .undo import glyph_restore, glyph_snapshot
    font = project.font
    plans = []
    for code in codes:
        plan = plan_composite(font, code)
        if plan is None:
            continue
        name = plan[0]
        if name in font and font[name].contours:
            continue
        plans.append((code, *plan))
    if not plans:
        return [], []
    created = [p[1] for p in plans if p[1] not in font]
    before = {(i, p[1]): glyph_snapshot(m.font[p[1]]) for i, m in enumerate(project.masters)
              for p in plans if p[1] in m.font}
    order_before = list(font.glyphOrder)
    messages: list[str] = []

    def do():
        messages.clear()
        for m in project.masters:
            for code, name, base, marks in plans:
                glyph = m.font[name] if name in m.font else m.font.newGlyph(name)
                glyph.unicodes = [code]
                messages.extend(place_marks(m.font, glyph, base, marks))
            m.font.glyphOrder = order_before + [n for n in created if n not in order_before]
        project.notify("glyphs", [p[1] for p in plans])

    def undo():
        for i, m in enumerate(project.masters):
            for _code, name, _base, _marks in plans:
                if (i, name) in before:
                    glyph_restore(m.font[name], before[(i, name)])
                elif name in m.font:
                    del m.font[name]
            m.font.glyphOrder = order_before
        project.notify("glyphs", [p[1] for p in plans])
    do()
    project.undo.push(f"Construire {len(plans)} accentué(s)", undo, do)
    return [p[1] for p in plans], list(dict.fromkeys(messages))
