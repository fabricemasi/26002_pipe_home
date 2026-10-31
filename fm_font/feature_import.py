"""Reprise des FEATURES d'une police compilée (sans Qt), à l'import :

- GSUB -> texte .fea : substitutions simples (1), multiples (2), alternatives (3), ligatures (4) et leurs
  extensions (7), en blocs `lookup` nommés appelés par chaque feature (ex. `feature liga { lookup gsub_3; } liga;`),
  drapeaux IgnoreMarks / IgnoreLigatures / IgnoreBaseGlyphs / RightToLeft gardés. Les lookups CONTEXTUELS (5, 6,
  8) ne sont pas décompilés : leur nombre est rendu pour le message d'import.
- GPOS marques -> ANCRES : MarkBase (4) et MarkMark (6) deviennent des ancres `top` / `_top`, `bottom` /
  `_bottom`… (nom choisi d'après la hauteur) ; ufo2ft régénère mark / mkmk à la compilation, comme pour une police
  dessinée ici. MarkLig (5) n'est pas repris.

Une police qui ne passe pas l'analyseur feaLib après reprise garde quand même le texte (l'éditeur de features
montre l'erreur) : rien n'est perdu en silence."""
from __future__ import annotations

from collections import OrderedDict

_FLAGS = ((1, "RightToLeft"), (2, "IgnoreBaseGlyphs"), (4, "IgnoreLigatures"), (8, "IgnoreMarks"))
_KEYWORDS = {"anon", "anonymous", "by", "contour", "cursive", "device", "enum", "enumerate", "exclude_dflt",
             "feature", "from", "ignore", "include", "include_dflt", "language", "languagesystem", "lookup",
             "lookupflag", "mark", "markclass", "nameid", "null", "parameters", "pos", "position", "required",
             "reversesub", "rsub", "script", "sub", "substitute", "subtable", "table", "useextension",
             "valuerecorddef", "base", "gdef", "head", "hhea", "name", "os_2", "stat", "vhea", "vmtx"}
CONTEXTUAL = (5, 6, 8)


def _name(glyph: str) -> str:
    return f"\\{glyph}" if glyph.lower() in _KEYWORDS else glyph


def _unwrap(lookup):
    """(type réel, sous-tables) : les extensions (7) sont déballées."""
    kind = lookup.LookupType
    subs = list(lookup.SubTable)
    if kind == 7 and subs:
        kind = subs[0].ExtensionLookupType
        subs = [s.ExtSubTable for s in subs]
    return kind, subs


def _rules(kind: int, subs) -> list[str]:
    rules = []
    for sub in subs:
        if kind == 1:
            rules += [f"sub {_name(a)} by {_name(b)};" for a, b in sub.mapping.items()]
        elif kind == 2:
            rules += [f"sub {_name(a)} by {' '.join(_name(g) for g in seq)};" for a, seq in sub.mapping.items()]
        elif kind == 3:
            rules += [f"sub {_name(a)} from [{' '.join(_name(g) for g in alts)}];"
                      for a, alts in sub.alternates.items()]
        elif kind == 4:
            for first, ligatures in sub.ligatures.items():
                for lig in ligatures:
                    parts = " ".join(_name(g) for g in [first] + list(lig.Component))
                    rules.append(f"sub {parts} by {_name(lig.LigGlyph)};")
    return rules


def gsub_to_fea(tt) -> tuple[str, int, list[str]]:
    """(texte .fea, nombre de lookups non repris, features reprises)."""
    if "GSUB" not in tt:
        return "", 0, []
    table = tt["GSUB"].table
    if not table.LookupList or not table.FeatureList:
        return "", 0, []
    lookups = table.LookupList.Lookup
    blocks, skipped = {}, set()
    for index, lookup in enumerate(lookups):
        kind, subs = _unwrap(lookup)
        if kind in CONTEXTUAL:
            skipped.add(index)
            continue
        rules = _rules(kind, subs)
        if not rules:
            continue
        flags = [label for bit, label in _FLAGS if lookup.LookupFlag & bit]
        head = f"    lookupflag {' '.join(flags)};\n" if flags else ""
        body = "".join(f"    {r}\n" for r in rules)
        blocks[index] = f"lookup gsub_{index} {{\n{head}{body}}} gsub_{index};\n"
    features: OrderedDict[str, list[int]] = OrderedDict()
    for record in table.FeatureList.FeatureRecord:
        indexes = features.setdefault(record.FeatureTag, [])
        for i in record.Feature.LookupListIndex:
            if i not in indexes:
                indexes.append(i)
    systems = []
    for script in table.ScriptList.ScriptRecord if table.ScriptList else ():
        if script.Script.DefaultLangSys is not None:
            systems.append((script.ScriptTag, "dflt"))
        systems += [(script.ScriptTag, rec.LangSysTag.strip() or "dflt") for rec in script.Script.LangSysRecord]
    systems = sorted(set(systems), key=lambda s: (s[0] != "DFLT", s[0], s[1] != "dflt", s[1]))
    if not any(s == ("DFLT", "dflt") for s in systems):
        systems.insert(0, ("DFLT", "dflt"))
    out = ["# Repris de la police importée (GSUB décompilé par fm_font).\n"]
    out += [f"languagesystem {script} {lang};\n" for script, lang in systems]
    used = sorted({i for indexes in features.values() for i in indexes if i in blocks})
    out += ["\n"] + [blocks[i] for i in used]
    kept = []
    for tag, indexes in features.items():
        calls = [i for i in indexes if i in blocks]
        if calls:
            kept.append(tag)
            out.append(f"\nfeature {tag} {{\n" + "".join(f"    lookup gsub_{i};\n" for i in calls) + f"}} {tag};\n")
    missing = len({i for indexes in features.values() for i in indexes if i in skipped})
    return ("".join(out) if kept else ""), missing, kept


def _anchor_name(kind: str, y: float, upm: int, taken: dict) -> str:
    base = "top" if y > upm * 0.25 else "bottom"
    name, n = base, 2
    while name in taken.values():
        name, n = f"{base}{n}", n + 1
    return name


def gpos_marks_to_anchors(tt, font) -> int:
    """Ancres reprises des lookups MarkBase / MarkMark ; renvoie le nombre d'ancres posées."""
    from .components import set_anchor
    if "GPOS" not in tt or not tt["GPOS"].table.LookupList:
        return 0
    upm = tt["head"].unitsPerEm
    count = 0
    for lookup in tt["GPOS"].table.LookupList.Lookup:
        kind, subs = lookup.LookupType, list(lookup.SubTable)
        if kind == 9 and subs:
            kind, subs = subs[0].ExtensionLookupType, [s.ExtSubTable for s in subs]
        if kind not in (4, 6):
            continue
        for sub in subs:
            marks = sub.Mark1Coverage.glyphs if kind == 6 else sub.MarkCoverage.glyphs
            bases = sub.Mark2Coverage.glyphs if kind == 6 else sub.BaseCoverage.glyphs
            mark_array = sub.Mark1Array if kind == 6 else sub.MarkArray
            base_records = sub.Mark2Array.Mark2Record if kind == 6 else sub.BaseArray.BaseRecord
            names: dict[int, str] = {}
            for klass in range(sub.ClassCount):
                ys = [getattr(rec, "Mark2Anchor" if kind == 6 else "BaseAnchor")[klass].YCoordinate
                      for rec in base_records
                      if getattr(rec, "Mark2Anchor" if kind == 6 else "BaseAnchor")[klass] is not None]
                existing = {k: v for k, v in names.items()}
                names[klass] = _anchor_name("base", sum(ys) / len(ys) if ys else upm, upm, existing)
            for glyph, record in zip(marks, mark_array.MarkRecord):
                if glyph in font:
                    a = record.MarkAnchor
                    set_anchor(font[glyph], "_" + names[record.Class], a.XCoordinate, a.YCoordinate)
                    count += 1
            for glyph, record in zip(bases, base_records):
                anchors = getattr(record, "Mark2Anchor" if kind == 6 else "BaseAnchor")
                for klass, a in enumerate(anchors):
                    if a is not None and glyph in font:
                        set_anchor(font[glyph], names[klass], a.XCoordinate, a.YCoordinate)
                        count += 1
    return count
