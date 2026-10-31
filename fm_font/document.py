"""Projet typographique (sans Qt) : une famille = un ou plusieurs MASTERS (fichiers UFO 3) décrits par un
Designspace. Format natif : UFO 3 + .designspace (données inconnues des UFO préservées par ufoLib2 : lib, data/,
images/). Un projet source n'est PAS une police compilée (voir `compile.py`).

Sauvegarde ATOMIQUE : chaque UFO est écrit dans un dossier temporaire voisin puis échangé avec l'ancien (copie
`.fmf-bak` gardée le temps de l'échange) ; une sauvegarde interrompue est réparée à la réouverture
(`recover_interrupted_save`). Les fichiers importés (TTF, OTF…) ne sont jamais réécrits : `path` est None tant que
l'utilisateur n'a pas choisi où enregistrer le projet source."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Callable

import ufoLib2
from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, InstanceDescriptor, SourceDescriptor

from . import glyph_info
from .undo import UndoStack, glyph_restore, glyph_snapshot

TMP_SUFFIX = ".fmf-tmp"
BAK_SUFFIX = ".fmf-bak"


class ProjectError(Exception):
    """Erreur lisible (ouverture, enregistrement) : le message est montré tel quel à l'utilisateur."""


class Master:
    """Un master : un UFO, son nom de style et sa position dans l'espace de variation."""

    def __init__(self, font: ufoLib2.Font, name: str, location: dict | None = None, path: Path | None = None):
        self.font = font
        self.name = name
        self.location = dict(location or {})
        self.path = Path(path) if path else None


def new_font(family: str, style: str, upm: int = 1000, ascender: int = 800, descender: int = -200,
             cap_height: int = 700, x_height: int = 500, italic_angle: float = 0.0) -> ufoLib2.Font:
    font = ufoLib2.Font()
    info = font.info
    info.familyName, info.styleName = family, style
    info.unitsPerEm = upm
    info.ascender, info.descender = ascender, descender
    info.capHeight, info.xHeight = cap_height, x_height
    info.italicAngle = italic_angle
    info.versionMajor, info.versionMinor = 1, 0
    notdef = font.newGlyph(".notdef")
    notdef.width = round(upm * 0.5)
    _draw_notdef(notdef, upm, ascender)
    space = font.newGlyph("space")
    space.unicodes = [0x20]
    space.width = round(upm * 0.25)
    font.glyphOrder = [".notdef", "space"]
    return font


def _draw_notdef(glyph, upm: int, ascender: int) -> None:
    """.notdef : rectangle évidé (obligatoire et attendu par les logiciels)."""
    w, m, t = glyph.width, round(upm * 0.05), round(upm * 0.05)
    top = round(ascender * 0.9)
    pen = glyph.getPen()
    pen.moveTo((m, 0)); pen.lineTo((m, top)); pen.lineTo((w - m, top)); pen.lineTo((w - m, 0)); pen.closePath()
    pen.moveTo((m + t, t)); pen.lineTo((w - m - t, t)); pen.lineTo((w - m - t, top - t)); pen.lineTo((m + t, top - t))
    pen.closePath()


def recover_interrupted_save(path: Path) -> str | None:
    """Répare une sauvegarde interrompue : l'original manquant est restauré depuis `.fmf-bak` ; un dossier
    temporaire abandonné est supprimé (l'original, complet, fait foi). Renvoie un message ou None."""
    path = Path(path)
    bak = path.with_name(path.name + BAK_SUFFIX)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    message = None
    if not path.exists() and bak.exists():
        os.replace(bak, path)
        message = f"Sauvegarde interrompue réparée : {path.name} restauré depuis sa copie de sécurité."
    elif bak.exists():
        _remove(bak)
    if tmp.exists():
        _remove(tmp)
        message = message or f"Sauvegarde interrompue ignorée pour {path.name} (l'original est intact)."
    return message


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def _replace(src: Path, dst: Path, tries: int = 5) -> None:
    """os.replace avec quelques essais : sous Windows, un dossier encore ouvert (explorateur, synchronisation)
    refuse brièvement d'être renommé."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.05 * (attempt + 1))


def save_ufo_atomic(font: ufoLib2.Font, path: Path) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    bak = path.with_name(path.name + BAK_SUFFIX)
    _remove(tmp)
    structure = "zip" if path.suffix.lower() == ".ufoz" else None
    try:
        font.save(tmp, overwrite=True, structure=structure)
    except Exception as exc:
        _remove(tmp)
        raise ProjectError(f"Enregistrement de {path.name} impossible : {exc}") from exc
    try:
        if path.exists():
            _remove(bak)
            _replace(path, bak)
        _replace(tmp, path)
    except OSError as exc:
        if not path.exists() and bak.exists():
            os.replace(bak, path)
        raise ProjectError(f"{path.name} : fichier occupé ({exc}). L'original est intact ; "
                           f"la nouvelle version est dans {tmp.name}.") from exc
    _remove(bak)


class FontProject:
    """Famille en cours d'édition. `masters[0]` est le master par défaut. Les opérations sur les glyphes
    s'appliquent à TOUS les masters (compatibilité des contours pour l'interpolation) sauf mention contraire.

    `listeners(kind, payload)` : kind = "glyph" (payload = (index du master, nom)), "glyphs" (liste des noms
    ajoutés / supprimés / renommés), "kerning", "info", "features", "masters", "undo"."""

    def __init__(self):
        self.masters: list[Master] = []
        self.axes: list[AxisDescriptor] = []
        self.instances: list[InstanceDescriptor] = []
        self.path: Path | None = None          # .designspace ou .ufo ; None = jamais enregistré
        self.source: Path | None = None        # fichier importé (jamais réécrit)
        self.undo = UndoStack()
        self.listeners: list[Callable[[str, object], None]] = []
        self.dirty_extra = False                # changement hors annulation (ex. métadonnées d'import)
        self.messages: list[str] = []           # messages d'ouverture (réparation, avertissements)
        self.revision = 0                       # +1 à chaque changement : clé des caches (aperçu compilé…)
        self.undo.listeners.append(lambda: self.notify("undo", None))

    # -- création / ouverture / enregistrement --

    @classmethod
    def new(cls, family: str = "Nouvelle famille", styles=("Regular",), upm: int = 1000, ascender: int = 800,
            descender: int = -200, cap_height: int = 700, x_height: int = 500,
            italic_angle: float = 0.0) -> "FontProject":
        project = cls()
        for index, style in enumerate(styles):
            font = new_font(family, style, upm, ascender, descender, cap_height, x_height, italic_angle)
            project.masters.append(Master(font, style, {"Weight": 400 + 300 * index} if len(styles) > 1 else {}))
        if len(styles) > 1:
            weights = [m.location["Weight"] for m in project.masters]
            project.axes.append(_axis("Weight", "wght", min(weights), weights[0], max(weights)))
        return project

    @classmethod
    def open(cls, path) -> "FontProject":
        path = Path(path)
        project = cls()
        message = recover_interrupted_save(path)
        if message:
            project.messages.append(message)
        if not path.exists():
            raise ProjectError(f"{path.name} : introuvable.")
        suffix = path.suffix.lower()
        if suffix == ".designspace":
            project._open_designspace(path)
        elif suffix in (".ufo", ".ufoz"):
            project.masters.append(Master(_open_ufo(path), "", {}, path))
            project.masters[0].name = project.masters[0].font.info.styleName or "Regular"
        else:
            raise ProjectError(f"{path.name} : ce n'est pas une source (.designspace, .ufo, .ufoz). "
                               "Une police compilée s'importe (fm_font.importer).")
        project.path = path
        return project

    def _open_designspace(self, path: Path) -> None:
        try:
            doc = DesignSpaceDocument.fromfile(path)
        except Exception as exc:
            raise ProjectError(f"{path.name} : Designspace illisible ({exc}).") from exc
        self.axes = list(doc.axes)
        self.instances = list(doc.instances)
        self._designspace_lib = dict(doc.lib)
        default = doc.findDefault()
        sources = sorted(doc.sources, key=lambda s: s is not default)
        for source in sources:
            ufo = Path(source.path) if source.path else path.parent / source.filename
            message = recover_interrupted_save(ufo)
            if message:
                self.messages.append(message)
            if source.layerName:
                self.messages.append(f"Source « {source.name} » sur un calque ({source.layerName}) : ignorée.")
                continue
            font = _open_ufo(ufo)
            self.masters.append(Master(font, source.styleName or font.info.styleName or ufo.stem,
                                       dict(source.location), ufo))
        if not self.masters:
            raise ProjectError(f"{path.name} : aucun master lisible.")

    def save(self, path=None) -> None:
        """Enregistre le projet (UFO atomiques + Designspace). `path` : .designspace ou .ufo (un seul master)."""
        target = Path(path) if path else self.path
        if target is None:
            raise ProjectError("Choisissez où enregistrer le projet source (.designspace ou .ufo).")
        suffix = target.suffix.lower()
        if suffix in (".ufo", ".ufoz"):
            if len(self.masters) != 1:
                raise ProjectError("Plusieurs masters : enregistrez en .designspace.")
            master = self.masters[0]
            save_ufo_atomic(master.font, target)
            master.path = target
        elif suffix == ".designspace":
            folder = target.parent / "masters"
            for master in self.masters:
                if master.path is None or master.path.suffix.lower() not in (".ufo", ".ufoz") or path:
                    master.path = folder / _ufo_name(self.family_name, master.name)
                master.path.parent.mkdir(parents=True, exist_ok=True)
                save_ufo_atomic(master.font, master.path)
            tmp = target.with_name(target.name + TMP_SUFFIX)      # même dossier : chemins relatifs identiques
            self.designspace(target).write(tmp)
            _replace(tmp, target)
        else:
            raise ProjectError(f"{target.name} : extension inconnue (.designspace, .ufo, .ufoz).")
        self.path = target
        self.dirty_extra = False
        self.undo.mark_clean()

    def designspace(self, target: Path | None = None) -> DesignSpaceDocument:
        """Document Designspace du projet (chemins relatifs à `target`, sinon absolus)."""
        doc = DesignSpaceDocument()
        doc.lib.update(getattr(self, "_designspace_lib", {}))
        for axis in self.axes:
            doc.addAxis(axis)
        default = self.default_location()
        for index, master in enumerate(self.masters):
            source = SourceDescriptor()
            source.font = master.font
            source.familyName = self.family_name
            source.styleName = master.name
            source.name = f"master.{index}"
            source.location = {a.name: master.location.get(a.name, default[a.name]) for a in self.axes}
            if master.path is not None:
                source.path = str(master.path)
                if target is not None:
                    source.filename = os.path.relpath(master.path, target.parent).replace("\\", "/")
            doc.addSource(source)
        for instance in self.instances:
            doc.addInstance(instance)
        return doc

    # -- état --

    @property
    def family_name(self) -> str:
        return self.masters[0].font.info.familyName or "Sans nom"

    def set_family_name(self, name: str) -> None:
        self.set_info("familyName", name, all_masters=True)

    def default_location(self) -> dict:
        return {a.name: a.default for a in self.axes}

    def is_dirty(self) -> bool:
        return self.dirty_extra or not self.undo.is_clean()

    def notify(self, kind: str, payload) -> None:
        self.revision += 1
        for listener in list(self.listeners):
            listener(kind, payload)

    @property
    def font(self) -> ufoLib2.Font:
        return self.masters[0].font

    def glyph_order(self) -> list[str]:
        font = self.font
        order = [n for n in font.glyphOrder if n in font]
        known = set(order)
        order.extend(sorted(n for n in font.keys() if n not in known))
        return order

    def glyph(self, name: str, master: int = 0):
        return self.masters[master].font[name]

    # -- informations de la famille / des masters --

    def set_info(self, attr: str, value, master: int = 0, all_masters: bool = False) -> None:
        targets = range(len(self.masters)) if all_masters else (master,)
        before = {i: getattr(self.masters[i].font.info, attr) for i in targets}
        if all(v == value for v in before.values()):
            return

        def apply(values):
            for i, v in values.items():
                setattr(self.masters[i].font.info, attr, v)
            self.notify("info", attr)
        after = {i: value for i in targets}
        apply(after)
        self.undo.push(f"Modifier {attr}", lambda: apply(before), lambda: apply(after))

    # -- glyphes : création, suppression, duplication, renommage (tous les masters) --

    def add_glyph(self, name: str, unicodes=None, width: int | None = None) -> None:
        if not name or name in self.font:
            raise ProjectError(f"Le glyphe « {name} » existe déjà." if name else "Nom de glyphe vide.")
        if unicodes is None:
            code = glyph_info.unicode_for_name(name)
            unicodes = [code] if code is not None else []
        width = round(self.font.info.unitsPerEm * 0.6) if width is None else width
        self._check_unicodes(unicodes, ignore=None)
        order_before = list(self.font.glyphOrder)

        def do():
            for m in self.masters:
                glyph = m.font.newGlyph(name)
                glyph.unicodes = list(unicodes)
                glyph.width = width
                m.font.glyphOrder = order_before + [name]
            self.notify("glyphs", [name])

        def undo():
            for m in self.masters:
                del m.font[name]
                m.font.glyphOrder = order_before
            self.notify("glyphs", [name])
        do()
        self.undo.push(f"Créer {name}", undo, do)

    def add_glyphs_for_unicodes(self, codes) -> list[str]:
        """Crée les glyphes manquants d'un jeu de caractères (un seul pas d'annulation)."""
        names = []
        cmap = self.cmap()
        for code in codes:
            if code in cmap:
                continue
            name = glyph_info.name_for_unicode(code)
            if name not in self.font and name not in names:
                names.append(name)
                cmap[code] = name
        if not names:
            return []
        order_before = list(self.font.glyphOrder)
        width = round(self.font.info.unitsPerEm * 0.6)

        def do():
            for m in self.masters:
                for name in names:
                    glyph = m.font.newGlyph(name)
                    glyph.unicodes = [glyph_info.unicode_for_name(name)] if glyph_info.unicode_for_name(name) else []
                    glyph.width = width
                m.font.glyphOrder = order_before + names
            self.notify("glyphs", names)

        def undo():
            for m in self.masters:
                for name in names:
                    del m.font[name]
                m.font.glyphOrder = order_before
            self.notify("glyphs", names)
        do()
        self.undo.push(f"Créer {len(names)} glyphes", undo, do)
        return names

    def delete_glyphs(self, names) -> None:
        names = [n for n in names if n in self.font]
        if not names:
            return
        users = {n: self.component_users(n) for n in names}
        blocked = {n: u for n, u in users.items() if set(u) - set(names)}
        if blocked:
            name, used = next(iter(blocked.items()))
            raise ProjectError(f"« {name} » sert de composant à : {', '.join(sorted(used)[:8])}. "
                               "Décomposez-les d'abord.")
        saved = [{n: glyph_snapshot(m.font[n]) for n in names} for m in self.masters]
        order_before = list(self.font.glyphOrder)
        kerning_before = [dict(m.font.kerning) for m in self.masters]
        groups_before = [{k: list(v) for k, v in m.font.groups.items()} for m in self.masters]
        gone = set(names)

        def do():
            for m in self.masters:
                for n in names:
                    del m.font[n]
                m.font.glyphOrder = [n for n in order_before if n not in gone]
                for pair in [p for p in m.font.kerning if p[0] in gone or p[1] in gone]:
                    del m.font.kerning[pair]
                for key, members in m.font.groups.items():
                    if any(g in gone for g in members):
                        m.font.groups[key] = [g for g in members if g not in gone]
            self.notify("glyphs", names)

        def undo():
            for i, m in enumerate(self.masters):
                for n in names:
                    glyph_restore(m.font.newGlyph(n), saved[i][n])
                m.font.glyphOrder = order_before
                m.font.kerning.clear()
                m.font.kerning.update(kerning_before[i])
                m.font.groups.clear()
                m.font.groups.update({k: list(v) for k, v in groups_before[i].items()})
            self.notify("glyphs", names)
        do()
        self.undo.push(f"Supprimer {len(names)} glyphe(s)", undo, do)

    def duplicate_glyph(self, name: str, new_name: str | None = None) -> str:
        if name not in self.font:
            raise ProjectError(f"« {name} » n'existe pas.")
        new_name = new_name or self.unique_name(f"{name}.copy")
        if new_name in self.font:
            raise ProjectError(f"Le glyphe « {new_name} » existe déjà.")
        order_before = list(self.font.glyphOrder)
        snaps = [glyph_snapshot(m.font[name]) for m in self.masters]

        def do():
            for i, m in enumerate(self.masters):
                glyph = m.font.newGlyph(new_name)
                glyph_restore(glyph, snaps[i])
                glyph.unicodes = []                       # un code Unicode n'appartient qu'à un glyphe
                order = list(order_before)
                order.insert(order.index(name) + 1 if name in order else len(order), new_name)
                m.font.glyphOrder = order
            self.notify("glyphs", [new_name])

        def undo():
            for m in self.masters:
                del m.font[new_name]
                m.font.glyphOrder = order_before
            self.notify("glyphs", [new_name])
        do()
        self.undo.push(f"Dupliquer {name}", undo, do)
        return new_name

    def rename_glyph(self, old: str, new: str) -> None:
        """Renomme partout : glyphe, ordre, composants qui l'utilisent, crénage, groupes."""
        if old == new:
            return
        if old not in self.font:
            raise ProjectError(f"« {old} » n'existe pas.")
        if not new or new in self.font:
            raise ProjectError(f"Le glyphe « {new} » existe déjà." if new else "Nom de glyphe vide.")

        def apply(a: str, b: str):
            for m in self.masters:
                font = m.font
                order = [b if n == a else n for n in font.glyphOrder]
                font.renameGlyph(a, b)
                font.glyphOrder = order
                for glyph in font:
                    for comp in glyph.components:
                        if comp.baseGlyph == a:
                            comp.baseGlyph = b
                for pair in [p for p in font.kerning if a in p]:
                    value = font.kerning.pop(pair)
                    font.kerning[tuple(b if x == a else x for x in pair)] = value
                for key, members in font.groups.items():
                    if a in members:
                        font.groups[key] = [b if g == a else g for g in members]
            self.notify("glyphs", [a, b])
        apply(old, new)
        self.undo.push(f"Renommer {old}", lambda: apply(new, old), lambda: apply(old, new))

    def set_unicodes(self, name: str, unicodes) -> None:
        unicodes = list(unicodes)
        self._check_unicodes(unicodes, ignore=name)
        before = list(self.font[name].unicodes)

        def apply(values):
            for m in self.masters:
                m.font[name].unicodes = list(values)
            self.notify("glyphs", [name])
        apply(unicodes)
        self.undo.push(f"Unicode de {name}", lambda: apply(before), lambda: apply(unicodes))

    def _check_unicodes(self, unicodes, ignore: str | None) -> None:
        cmap = self.cmap()
        for code in unicodes:
            owner = cmap.get(code)
            if owner is not None and owner != ignore:
                raise ProjectError(f"U+{code:04X} est déjà attribué à « {owner} ».")

    def cmap(self) -> dict[int, str]:
        return {code: glyph.name for glyph in self.font for code in glyph.unicodes}

    def unique_name(self, base: str) -> str:
        if base not in self.font:
            return base
        index = 1
        while f"{base}{index}" in self.font:
            index += 1
        return f"{base}{index}"

    def component_users(self, name: str) -> list[str]:
        return [g.name for g in self.font if any(c.baseGlyph == name for c in g.components)]

    # -- édition d'un glyphe (un pas d'annulation par geste) --

    def begin_edit(self, name: str, master: int = 0) -> tuple:
        """Instantané AVANT un geste (appelé au clic, jamais pendant le mouvement)."""
        return (master, name, glyph_snapshot(self.masters[master].font[name]))

    def end_edit(self, token: tuple, label: str) -> bool:
        """Pousse l'étape si le glyphe a changé depuis `begin_edit`. Renvoie True si une étape a été créée."""
        master, name, before = token
        glyph = self.masters[master].font[name]
        after = glyph_snapshot(glyph)
        if after == before:
            return False

        def apply(snap):
            glyph_restore(self.masters[master].font[name], snap)
            self.notify("glyph", (master, name))
        self.undo.push(label, lambda: apply(before), lambda: apply(after))
        self.notify("glyph", (master, name))
        return True

    def edit_glyph(self, name: str, label: str, fn: Callable, master: int | None = 0) -> bool:
        """Action ponctuelle : `fn(glyph)` sur un master (ou tous si master=None), un seul pas d'annulation."""
        indexes = range(len(self.masters)) if master is None else (master,)
        befores = {i: glyph_snapshot(self.masters[i].font[name]) for i in indexes}
        for i in indexes:
            fn(self.masters[i].font[name])
        afters = {i: glyph_snapshot(self.masters[i].font[name]) for i in indexes}
        if afters == befores:
            return False

        def apply(snaps):
            for i, snap in snaps.items():
                glyph_restore(self.masters[i].font[name], snap)
                self.notify("glyph", (i, name))
        self.undo.push(label, lambda: apply(befores), lambda: apply(afters))
        for i in indexes:
            self.notify("glyph", (i, name))
        return True

    # -- instances nommées (Designspace : fvar de la police variable, instances statiques) --

    def set_instances(self, entries) -> None:
        """`entries` : [(nom de style, {axe: valeur})] ; un pas d'annulation. Valeurs hors des axes refusées."""
        axes = {a.name: a for a in self.axes}
        built = []
        for name, location in entries:
            for axis_name, value in location.items():
                axis = axes.get(axis_name)
                if axis is None:
                    raise ProjectError(f"Instance « {name} » : axe « {axis_name} » inconnu.")
                if not axis.minimum <= value <= axis.maximum:
                    raise ProjectError(f"Instance « {name} » : {axis_name} {value:g} hors de "
                                       f"{axis.minimum:g}–{axis.maximum:g}.")
            inst = InstanceDescriptor()
            inst.familyName = self.family_name
            inst.styleName = name
            inst.location = {a: location.get(a, axes[a].default) for a in axes}
            built.append(inst)
        before = list(self.instances)

        def apply(values):
            self.instances = list(values)
            self.notify("masters", None)
        apply(built)
        self.undo.push("Instances", lambda: apply(before), lambda: apply(built))

    # -- masters --

    def add_master(self, name: str, location: dict, copy_from: int = 0) -> Master:
        """Nouveau master, copie d'un autre (contours compatibles par construction)."""
        import copy
        font = copy.deepcopy(self.masters[copy_from].font)
        font.info.styleName = name
        master = Master(font, name, location)
        self.masters.append(master)
        self.undo.push(f"Master {name}", lambda: (self.masters.remove(master), self.notify("masters", None)),
                       lambda: (self.masters.append(master), self.notify("masters", None)))
        self.notify("masters", None)
        return master


def _axis(name: str, tag: str, minimum: float, default: float, maximum: float) -> AxisDescriptor:
    axis = AxisDescriptor()
    axis.name, axis.tag = name, tag
    axis.minimum, axis.default, axis.maximum = minimum, default, maximum
    axis.labelNames = {"fr": name, "en": name}
    return axis


def _ufo_name(family: str, style: str) -> str:
    safe = "".join(c for c in f"{family}-{style}".replace(" ", "") if c.isalnum() or c in "-_.")
    return f"{safe or 'Master'}.ufo"


def _open_ufo(path: Path) -> ufoLib2.Font:
    try:
        return ufoLib2.Font.open(path, lazy=False)
    except Exception as exc:
        raise ProjectError(f"{path.name} : UFO illisible ({exc}).") from exc
