"""Compilation (sans Qt) : UFO -> OTF (CFF) / TTF (glyf) / WOFF / WOFF2, et Designspace -> police variable
(fvar, gvar, avar, STAT, instances nommées) par ufo2ft / fontTools.varLib. Aucun compilateur maison.

L'export passe d'abord par `validation.diagnose` : un problème BLOQUANT arrête l'export avec son message."""
from __future__ import annotations

import io
from pathlib import Path

from fontTools.designspaceLib import InstanceDescriptor
from fontTools.ttLib import TTFont

FORMATS = ("otf", "ttf", "woff", "woff2", "otf-hinted", "ttf-hinted", "woff-hinted", "woff2-hinted", "variable-ttf",
           "variable-woff2")


class CompileError(Exception):
    pass


def _ufo2ft():
    import ufo2ft
    return ufo2ft


def compile_static(font, fmt: str = "ttf", remove_overlaps: bool = True) -> TTFont:
    """Police statique d'un UFO. `fmt` : otf / ttf / woff / woff2 (WOFF = enveloppe du TTF)."""
    from .color import compile_layers
    ufo2ft = _ufo2ft()
    try:
        with compile_layers(font):                        # dégradés COLR v1 recalculés sur le dessin actuel
            if fmt == "otf":
                tt = ufo2ft.compileOTF(font, removeOverlaps=remove_overlaps, optimizeCFF=1)
            else:
                tt = ufo2ft.compileTTF(font, removeOverlaps=remove_overlaps, reverseDirection=True)
    except Exception as exc:
        raise CompileError(_readable(exc)) from exc
    if fmt in ("woff", "woff2"):
        tt.flavor = fmt
    return tt


def compile_variable(project, fmt: str = "ttf") -> TTFont:
    """Police variable TrueType depuis le Designspace du projet (masters compatibles exigés)."""
    if len(project.masters) < 2 or not project.axes:
        raise CompileError("Une police variable demande au moins deux masters et un axe.")
    from .interpolation import incompatibilities
    problems = incompatibilities(project)
    if problems:
        first = problems[0]
        raise CompileError(f"Masters incompatibles ({len(problems)} problème(s)) : {first}")
    doc = project.designspace(project.path if project.path and project.path.suffix == ".designspace" else None)
    for source, master in zip(doc.sources, project.masters):
        source.font = master.font
    if not doc.instances:
        _default_instances(project, doc)
    from .color import compile_layers
    try:
        with compile_layers(*(m.font for m in project.masters)):
            tt = _ufo2ft().compileVariableTTF(doc, optimizeGvar=True)
    except Exception as exc:
        raise CompileError(_readable(exc)) from exc
    if fmt == "woff2":
        tt.flavor = "woff2"
    return tt


def _default_instances(project, doc) -> None:
    """Instances nommées par défaut : une par master (fvar en a besoin pour être utile)."""
    default = project.default_location()
    for master in project.masters:
        inst = InstanceDescriptor()
        inst.familyName = project.family_name
        inst.styleName = master.name
        inst.location = {a.name: master.location.get(a.name, default[a.name]) for a in project.axes}
        doc.addInstance(inst)


def to_bytes(tt: TTFont) -> bytes:
    buffer = io.BytesIO()
    tt.save(buffer)
    return buffer.getvalue()


def export(project, path, fmt: str | None = None, master: int = 0, check: bool = True,
           instance: dict | None = None, instance_name: str = "Instance") -> list:
    """Compile et écrit `path` (format d'après l'extension si `fmt` est None). Écriture atomique (fichier
    temporaire puis remplacement). `otf-hinted` : CFF hinté par otfautohint ; autres `*-hinted` : TrueType hinté
    par ttfautohint. `instance` : position dans
    l'espace de variation ({axe: valeur}) d'une instance STATIQUE interpolée (masters compatibles exigés).
    Renvoie les diagnostics non bloquants."""
    path = Path(path)
    fmt = fmt or path.suffix.lower().lstrip(".")
    if fmt not in FORMATS:
        raise CompileError(f"Format inconnu : {fmt}")
    if project.source is not None and path.resolve() == Path(project.source).resolve():
        raise CompileError("Le fichier importé n'est jamais écrasé : choisissez un autre nom.")
    notes = []
    if check:
        from .validation import BLOCKING, diagnose
        found = diagnose(project, variable=fmt.startswith("variable"))
        blocking = [d for d in found if d.level == BLOCKING]
        if blocking:
            raise CompileError(f"Export arrêté : {blocking[0]}" + (f" (+{len(blocking) - 1} autre(s))"
                                                                    if len(blocking) > 1 else ""))
        notes = found
    if fmt.startswith("variable"):
        tt = compile_variable(project, "woff2" if fmt.endswith("woff2") else "ttf")
        data = to_bytes(tt)
    else:
        font = project.masters[master].font
        if instance is not None:
            from .interpolation import InterpolationError, instance_font
            try:
                font = instance_font(project, instance, instance_name)
            except InterpolationError as exc:
                raise CompileError(f"Instance impossible : {exc}") from exc
        base = fmt.replace("-hinted", "")
        if fmt == "otf-hinted":
            from .hinting import HintingError, autohint_cff, with_ps_hinting_info
            try:
                with with_ps_hinting_info(font):
                    otf = to_bytes(compile_static(font, "otf"))
                tt = TTFont(io.BytesIO(autohint_cff(otf)))
            except HintingError as exc:
                raise CompileError(str(exc)) from exc
        elif fmt.endswith("-hinted"):
            from .hinting import HintingError, autohint
            try:
                hinted = autohint(to_bytes(compile_static(font, "ttf")))
            except HintingError as exc:
                raise CompileError(str(exc)) from exc
            tt = TTFont(io.BytesIO(hinted))
            if base in ("woff", "woff2"):
                tt.flavor = base
        else:
            tt = compile_static(font, base)
        data = to_bytes(tt)
    tmp = path.with_name(path.name + ".fmf-tmp")
    tmp.write_bytes(data)
    import os
    os.replace(tmp, path)
    return notes


def _readable(exc: Exception) -> str:
    text = f"{type(exc).__name__} : {exc}"
    if "FeatureLibError" in text or "feaLib" in type(exc).__module__:
        from .features import from_exception
        return f"Features : {from_exception(exc)}"
    return text
