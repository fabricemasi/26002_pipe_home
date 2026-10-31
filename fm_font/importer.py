"""Import (sans Qt) : polices compilées TTF / OTF / WOFF / WOFF2 -> projet source (le fichier importé n'est
JAMAIS réécrit : `project.source` le garde, `project.path` reste None), UFO / Designspace (ouverture directe),
SVG -> contours d'un glyphe.

Repris d'une police compilée : contours (et composants TrueType), chasses, Unicode, noms, métriques verticales,
angle d'italique, crénage GPOS (paires simples et classes) ou table kern. NON repris (dit à l'utilisateur dans
`project.messages`) : features GSUB / GPOS autres que le crénage (pas de décompilateur .fea fiable), hinting."""
from __future__ import annotations

from pathlib import Path

from fontTools.pens.pointPen import SegmentToPointPen
from fontTools.ttLib import TTFont

from .document import FontProject, Master, new_font


def open_any(path) -> FontProject:
    path = Path(path)
    if path.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2"):
        return import_binary(path)
    return FontProject.open(path)


def import_binary(path) -> FontProject:
    path = Path(path)
    try:
        tt = TTFont(path, lazy=False)
    except Exception as exc:
        from .document import ProjectError
        raise ProjectError(f"{path.name} : police illisible ({exc}).") from exc
    if "fvar" in tt:
        tt_messages = ["Police variable importée à sa position par défaut (les masters ne se reconstruisent pas)."]
    else:
        tt_messages = []
    name = tt["name"]
    family = (name.getBestFamilyName() or path.stem)
    style = (name.getBestSubFamilyName() or "Regular")
    upm = tt["head"].unitsPerEm
    os2 = tt["OS/2"] if "OS/2" in tt else None
    hhea = tt["hhea"]
    font = new_font(family, style, upm, ascender=getattr(os2, "sTypoAscender", hhea.ascent),
                    descender=getattr(os2, "sTypoDescender", hhea.descent),
                    cap_height=getattr(os2, "sCapHeight", 0) or round(upm * 0.7),
                    x_height=getattr(os2, "sxHeight", 0) or round(upm * 0.5),
                    italic_angle=tt["post"].italicAngle if "post" in tt else 0)
    for glyph_name in list(font.keys()):
        del font[glyph_name]
    head = tt["head"]
    font.info.versionMajor = int(head.fontRevision)
    font.info.versionMinor = int(round((head.fontRevision % 1) * 1000))
    for attr, name_id in (("copyright", 0), ("trademark", 7), ("openTypeNameDesigner", 9),
                          ("openTypeNameLicense", 13), ("openTypeNameLicenseURL", 14)):
        text = name.getDebugName(name_id)
        if text:
            setattr(font.info, attr, text)
    glyph_set = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    cmap = tt.getBestCmap() or {}
    unicodes: dict[str, list[int]] = {}
    for code, gname in cmap.items():
        unicodes.setdefault(gname, []).append(code)
    hmtx = tt["hmtx"].metrics
    for gname in order:
        glyph = font.newGlyph(gname)
        glyph.width = hmtx[gname][0]
        glyph.unicodes = sorted(unicodes.get(gname, []))
        source = glyph_set[gname]
        pen = glyph.getPointPen()
        if hasattr(source, "drawPoints"):
            try:
                source.drawPoints(pen)
                continue
            except (NotImplementedError, TypeError, AttributeError):
                glyph.clearContours()
                glyph.clearComponents()
        source.draw(SegmentToPointPen(pen))
    font.glyphOrder = order
    _import_kerning(tt, font)
    project = FontProject()
    project.masters.append(Master(font, style, {}, None))
    project.source = path
    project.messages += tt_messages
    if "GSUB" in tt or ("GPOS" in tt and _has_other_gpos(tt)):
        project.messages.append("Features OpenType (GSUB / GPOS hors crénage) non reprises : réécrivez-les dans "
                                "l'éditeur de features.")
    project.dirty_extra = True
    return project


def _import_kerning(tt, font) -> None:
    if "GPOS" in tt:
        gpos = tt["GPOS"].table
        if gpos.LookupList:
            kern_lookups = set()
            for rec in gpos.FeatureList.FeatureRecord if gpos.FeatureList else ():
                if rec.FeatureTag == "kern":
                    kern_lookups.update(rec.Feature.LookupListIndex)
            for index in sorted(kern_lookups):
                lookup = gpos.LookupList.Lookup[index]
                for sub in lookup.SubTable:
                    if lookup.LookupType == 9:
                        sub = sub.ExtSubTable
                    if getattr(sub, "LookupType", 2) == 2 or lookup.LookupType in (2, 9):
                        _pair_pos(sub, font)
    elif "kern" in tt:
        for table in tt["kern"].kernTables:
            for pair, value in getattr(table, "kernTable", {}).items():
                font.kerning.setdefault(pair, value)


def _pair_pos(sub, font) -> None:
    if not hasattr(sub, "Format"):
        return
    if sub.Format == 1:
        firsts = sub.Coverage.glyphs
        for left, pairset in zip(firsts, sub.PairSet):
            for rec in pairset.PairValueRecord:
                value = getattr(rec.Value1, "XAdvance", 0) if rec.Value1 else 0
                if value:
                    font.kerning.setdefault((left, rec.SecondGlyph), value)
    elif sub.Format == 2:
        covered = sub.Coverage.glyphs
        class1: dict[int, list[str]] = {}
        defs1 = sub.ClassDef1.classDefs if sub.ClassDef1 else {}
        for g in covered:
            class1.setdefault(defs1.get(g, 0), []).append(g)
        class2: dict[int, list[str]] = {}
        for g, c in (sub.ClassDef2.classDefs if sub.ClassDef2 else {}).items():
            class2.setdefault(c, []).append(g)
        names1 = {}
        for c, glyphs in class1.items():
            names1[c] = _group(font, "public.kern1.", glyphs)
        names2 = {c: _group(font, "public.kern2.", glyphs) for c, glyphs in class2.items()}
        for c1, rec1 in enumerate(sub.Class1Record):
            if c1 not in names1:
                continue
            for c2, rec2 in enumerate(rec1.Class2Record):
                if c2 == 0 or c2 not in names2:
                    continue
                value = getattr(rec2.Value1, "XAdvance", 0) if rec2.Value1 else 0
                if value:
                    font.kerning.setdefault((names1[c1], names2[c2]), value)


def _group(font, prefix: str, glyphs) -> str:
    glyphs = sorted(glyphs, key=lambda g: (len(g), g))
    taken = {g for name, members in font.groups.items() if name.startswith(prefix) for g in members}
    glyphs = [g for g in glyphs if g not in taken]
    for name, members in font.groups.items():
        if name.startswith(prefix) and sorted(members) == sorted(glyphs):
            return name
    key = f"{prefix}{glyphs[0] if glyphs else 'vide'}"
    index = 1
    while key in font.groups:
        key = f"{prefix}{glyphs[0]}{index}"
        index += 1
    font.groups[key] = glyphs
    return key


def _has_other_gpos(tt) -> bool:
    gpos = tt["GPOS"].table
    return bool(gpos.FeatureList) and any(r.FeatureTag != "kern" for r in gpos.FeatureList.FeatureRecord)


def import_svg(path, glyph, upm: int, ascender: float, fit_height: float | None = None) -> None:
    """Ajoute les tracés d'un SVG au glyphe (y retourné ; mis à l'échelle de `fit_height` unités s'il est
    donné, sinon 1 px = 1 unité ; posé sur la ligne de base)."""
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.svgLib.path import SVGPath
    svg = SVGPath(str(path))
    recorder = RecordingPen()
    svg.draw(recorder)
    from fontTools.pens.boundsPen import BoundsPen
    bounds_pen = BoundsPen(None)
    recorder.replay(bounds_pen)
    if bounds_pen.bounds is None:
        return
    x0, y0, x1, y1 = bounds_pen.bounds
    scale = fit_height / (y1 - y0) if fit_height and y1 > y0 else 1.0
    # y SVG vers le bas -> y police vers le haut ; bas du dessin sur la ligne de base
    matrix = (scale, 0, 0, -scale, -x0 * scale, y1 * scale)
    recorder.replay(TransformPen(glyph.getPen(), matrix))
