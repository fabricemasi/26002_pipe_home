"""AXES de variation (sans Qt) : édition des axes, CARTES d'axes (avar), positions des masters, instances sur
plusieurs axes.

Conventions du Designspace : `minimum` / `default` / `maximum` d'un axe sont en coordonnées UTILISATEUR (celles
de fvar, ex. graisse 100–900) ; les positions des masters et des instances sont en coordonnées de CONCEPTION
(celles des dessins, ex. épaisseur du fût 20–200). La CARTE (`axis.map`, paires utilisateur -> conception) relie
les deux ; sans carte elles sont égales. La carte devient la table avar de la police variable.

Saisie texte (panneau Masters) :
- axes : « Weight wght 100 400 900 carte 100>20 400>80 900>200 ; Width wdth 75 100 125 »
- position : « Weight=700 Width=100 » (noms ou étiquettes d'axe)
- instances : « Light 300, Bold Condensed wght=700 wdth=75 » (un nombre seul = premier axe)."""
from __future__ import annotations

import copy

from .document import ProjectError, _axis


def design_value(axis, user: float) -> float:
    return axis.map_forward(user) if axis.map else user


def user_value(axis, design: float) -> float:
    return axis.map_backward(design) if axis.map else design


def design_ranges(project) -> dict:
    """{axe: (min, défaut, max)} en coordonnées de CONCEPTION (normalisation de l'interpolation)."""
    return {a.name: (design_value(a, a.minimum), design_value(a, a.default), design_value(a, a.maximum))
            for a in project.axes}


def default_design(project) -> dict:
    return {a.name: design_value(a, a.default) for a in project.axes}


def _number(text: str) -> float:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        raise ProjectError(f"« {text} » n'est pas un nombre.") from None


def _fmt(value: float) -> str:
    return f"{value:g}"


# -- axes --

def format_axes(axes) -> str:
    parts = []
    for a in axes:
        text = f"{a.name} {a.tag} {_fmt(a.minimum)} {_fmt(a.default)} {_fmt(a.maximum)}"
        if a.map:
            text += " carte " + " ".join(f"{_fmt(u)}>{_fmt(d)}" for u, d in a.map)
        parts.append(text)
    return " ; ".join(parts)


def parse_axes(text: str) -> list[dict]:
    specs = []
    for part in text.split(";"):
        tokens = part.split()
        if not tokens:
            continue
        if len(tokens) < 5:
            raise ProjectError(f"Axe « {part.strip()} » : « Nom étiquette min défaut max [carte u>c …] ».")
        name, tag = tokens[0], tokens[1]
        minimum, default, maximum = (_number(t) for t in tokens[2:5])
        mapping = []
        rest = tokens[5:]
        if rest and rest[0].lower() in ("carte", "map"):
            rest = rest[1:]
        for pair in rest:
            user, sep, design = pair.partition(">")
            if not sep:
                raise ProjectError(f"Carte de « {name} » : « {pair} » doit s'écrire utilisateur>conception.")
            mapping.append((_number(user), _number(design)))
        specs.append({"name": name, "tag": tag, "minimum": minimum, "default": default, "maximum": maximum,
                      "map": mapping})
    return specs


def _check_spec(spec: dict) -> None:
    name, tag = spec["name"], spec["tag"]
    if not (1 <= len(tag) <= 4 and tag.isascii() and tag.isprintable()):
        raise ProjectError(f"Axe « {name} » : l'étiquette « {tag} » doit faire 1 à 4 caractères ASCII.")
    if not spec["minimum"] <= spec["default"] <= spec["maximum"] or spec["minimum"] == spec["maximum"]:
        raise ProjectError(f"Axe « {name} » : il faut min ≤ défaut ≤ max et min < max.")
    mapping = sorted(spec["map"])
    for (u0, d0), (u1, d1) in zip(mapping, mapping[1:]):
        if u1 <= u0 or d1 <= d0:
            raise ProjectError(f"Carte de « {name} » : les valeurs doivent croître des deux côtés "
                               f"({_fmt(u0)}>{_fmt(d0)} puis {_fmt(u1)}>{_fmt(d1)}).")
    for u, _d in mapping:
        if not spec["minimum"] <= u <= spec["maximum"]:
            raise ProjectError(f"Carte de « {name} » : {_fmt(u)} hors de l'axe "
                               f"({_fmt(spec['minimum'])}–{_fmt(spec['maximum'])}).")
    if mapping and not {spec["minimum"], spec["default"], spec["maximum"]} <= {u for u, _d in mapping}:
        raise ProjectError(f"Carte de « {name} » : elle doit donner le min, le défaut et le max de l'axe "
                           f"({_fmt(spec['minimum'])}, {_fmt(spec['default'])}, {_fmt(spec['maximum'])}).")
    spec["map"] = mapping


def set_axes(project, specs: list[dict]) -> None:
    """Remplace les axes (un pas d'annulation). Masters et instances GARDENT leur position UTILISATEUR : changer la
    carte recalcule leur position de conception (corrigez-la ensuite dans « Position du master »). Un axe renommé
    garde ses positions (même rang) ; un axe ajouté les place à son défaut ; un axe retiré disparaît. Refus si un
    master sort d'un axe ou si deux masters tombent au même endroit."""
    names = [s["name"] for s in specs]
    tags = [s["tag"] for s in specs]
    if len(set(names)) != len(names) or len(set(tags)) != len(tags):
        raise ProjectError("Deux axes ont le même nom ou la même étiquette.")
    for spec in specs:
        _check_spec(spec)
    old_axes = list(project.axes)
    built = []
    for spec in specs:
        axis = _axis(spec["name"], spec["tag"], spec["minimum"], spec["default"], spec["maximum"])
        axis.map = list(spec["map"])
        built.append(axis)

    def relocate(location: dict) -> dict:
        out = {}
        by_name = {a.name: a for a in old_axes}
        for rank, axis in enumerate(built):
            old = by_name.get(axis.name) or (old_axes[rank] if rank < len(old_axes) else None)
            if old is not None and old.name in location:
                out[axis.name] = design_value(axis, user_value(old, location[old.name]))
            else:
                out[axis.name] = design_value(axis, axis.default)
        return out

    masters_after = [relocate(m.location) for m in project.masters]
    for master, loc in zip(project.masters, masters_after):
        for axis in built:
            low, high = sorted((design_value(axis, axis.minimum), design_value(axis, axis.maximum)))
            if not low <= loc[axis.name] <= high:
                raise ProjectError(f"Master « {master.name} » : {axis.name} {_fmt(loc[axis.name])} hors de l'axe "
                                   f"(conception {_fmt(low)}–{_fmt(high)}).")
    if len(project.masters) > 1:
        seen = {}
        for master, loc in zip(project.masters, masters_after):
            key = tuple(sorted(loc.items()))
            if key in seen:
                raise ProjectError(f"Masters « {seen[key]} » et « {master.name} » au même endroit.")
            seen[key] = master.name
    instances_after = []
    for inst in project.instances:
        clone = copy.deepcopy(inst)
        clone.location = relocate(dict(inst.location))
        instances_after.append(clone)
    before = (copy.deepcopy(project.axes), [dict(m.location) for m in project.masters], list(project.instances))
    after = (built, masters_after, instances_after)

    def apply(state):
        axes, locations, instances = state
        project.axes = copy.deepcopy(axes)
        for m, loc in zip(project.masters, locations):
            m.location = dict(loc)
        project.instances = list(instances)
        project.notify("masters", None)
    apply(after)
    project.undo.push("Axes", lambda: apply(before), lambda: apply(after))


# -- positions --

def _axis_named(project, key: str):
    for a in project.axes:
        if key in (a.name, a.tag):
            return a
    raise ProjectError(f"Axe « {key} » inconnu (axes : {', '.join(a.name for a in project.axes) or 'aucun'}).")


def parse_location(project, text: str, user: bool = False) -> dict:
    """« Weight=700 wdth=75 » -> {axe: valeur} ; `user` : valeurs en coordonnées utilisateur, rendues en
    conception."""
    location = {}
    for token in text.replace(",", " ").split():
        key, sep, value = token.partition("=")
        if not sep:
            raise ProjectError(f"« {token} » : écrire axe=valeur.")
        axis = _axis_named(project, key)
        number = _number(value)
        location[axis.name] = design_value(axis, number) if user else number
    return location


def format_location(project, location: dict, user: bool = False) -> str:
    return " ".join(f"{a.name}={_fmt(round(user_value(a, location[a.name]) if user else location[a.name], 3))}"
                    for a in project.axes if a.name in location)


def set_master_location(project, index: int, location: dict) -> None:
    """Position de CONCEPTION d'un master (un pas d'annulation) ; refus hors des axes ou sur un autre master."""
    master = project.masters[index]
    after = dict(master.location)
    after.update(location)
    for axis in project.axes:
        low, high = sorted((design_value(axis, axis.minimum), design_value(axis, axis.maximum)))
        value = after.setdefault(axis.name, design_value(axis, axis.default))
        if not low <= value <= high:
            raise ProjectError(f"{axis.name} {_fmt(value)} hors de l'axe (conception {_fmt(low)}–{_fmt(high)}).")
    for other in project.masters:
        if other is not master and all(other.location.get(k) == v for k, v in after.items()):
            raise ProjectError(f"« {other.name} » est déjà à cet endroit.")
    before = dict(master.location)

    def apply(loc):
        master.location = dict(loc)
        project.notify("masters", None)
    apply(after)
    project.undo.push(f"Position de {master.name}", lambda: apply(before), lambda: apply(after))


# -- instances --

def format_instances(project) -> str:
    if not project.axes:
        return ""
    if len(project.axes) == 1:
        axis = project.axes[0]
        return ", ".join(f"{i.styleName} {_fmt(round(user_value(axis, i.location.get(axis.name, 0)), 3))}"
                         for i in project.instances)
    return ", ".join(f"{i.styleName} {format_location(project, dict(i.location), user=True)}"
                     for i in project.instances)


def parse_instances(project, text: str) -> list[tuple[str, dict]]:
    """Entrées pour `FontProject.set_instances` (coordonnées UTILISATEUR)."""
    if not project.axes:
        raise ProjectError("Aucun axe : ajoutez un master ou des axes d'abord.")
    entries = []
    for part in text.split(","):
        tokens = part.split()
        if not tokens:
            continue
        assigned = [t for t in tokens if "=" in t]
        words = [t for t in tokens if "=" not in t]
        location = {}
        if assigned:
            for token in assigned:
                key, _sep, value = token.partition("=")
                location[_axis_named(project, key).name] = _number(value)
        elif len(words) >= 2:
            location[project.axes[0].name] = _number(words.pop())
        if not words or not location:
            raise ProjectError(f"Instance « {part.strip()} » : « Nom valeur » ou « Nom axe=valeur … ».")
        entries.append((" ".join(words), location))
    return entries
