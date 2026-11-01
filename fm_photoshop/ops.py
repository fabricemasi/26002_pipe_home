"""Opérations sur le document (SANS Qt). Chacune MODIFIE le document et rend l'étape d'annulation correspondante
(`history.Command`, déjà appliquée) : l'appelant la pousse dans l'historique (`session.Session.do`).

Les structures (ordre, groupes, masques, réglages) sont modifiées par des fonctions faire / défaire qui gardent les
OBJETS calques (leurs pixels ne sont jamais copiés pour une annulation de structure)."""
from __future__ import annotations

import copy

import numpy as np

from . import compose as C
from .history import CallCommand, Compound, TilesCommand
from .model import BLEND_MODES, Layer, Mask
from .planes import Plane, rect_intersect, rect_union


def _call(label, do, undo, rect=None):
    do()
    return CallCommand(label, do, undo, rect)


def _unique_name(doc, base: str) -> str:
    names = {layer.name for layer in doc.walk()}
    if base not in names:
        return base
    n = 2
    while f"{base} {n}" in names:
        n += 1
    return f"{base} {n}"


# -- calques --
def add_layer(doc, name: str = "Calque", parent: Layer | None = None, index: int | None = None, kind="raster"):
    """Nouveau calque transparent (ou groupe). Rend (calque, étape)."""
    layer = Layer(_unique_name(doc, name), kind)
    siblings = parent.children if parent is not None else doc.layers
    at = len(siblings) if index is None else max(0, min(index, len(siblings)))
    cmd = _call("Nouveau groupe" if kind == "group" else "Nouveau calque",
                lambda: siblings.insert(min(at, len(siblings)), layer), lambda: siblings.remove(layer))
    return layer, cmd


def add_layer_with_pixels(doc, rgba: np.ndarray, x: int, y: int, name: str, index: int | None = None):
    layer, cmd = add_layer(doc, name, index=index)
    layer.pix.set_all(x, y, rgba)
    return layer, cmd


def remove_layer(doc, layer: Layer):
    siblings, at = doc.parent_list(layer)
    if siblings is None:
        raise ValueError("Calque introuvable.")
    if len(doc.layers) == 1 and siblings is doc.layers:
        raise ValueError("Le document doit garder au moins un calque.")
    return _call("Supprimer le calque", lambda: siblings.remove(layer), lambda: siblings.insert(at, layer))


def _clone(layer: Layer) -> Layer:
    twin = Layer(layer.name, layer.kind)
    for key in Layer.PROPS:
        setattr(twin, key, getattr(layer, key))
    twin.extra = copy.deepcopy(layer.extra)
    twin.source = copy.deepcopy(layer.source)
    if layer.pix is not None:
        if layer.pix.data is not None:
            twin.pix.set_all(layer.pix.x, layer.pix.y, layer.pix.data.copy())
    if layer.mask is not None:
        twin.mask = Mask(Plane(1, layer.mask.plane.fill), layer.mask.enabled)
        if layer.mask.plane.data is not None:
            twin.mask.plane.set_all(layer.mask.plane.x, layer.mask.plane.y, layer.mask.plane.data.copy())
    twin.children = [_clone(c) for c in layer.children]
    return twin


def duplicate_layer(doc, layer: Layer):
    siblings, at = doc.parent_list(layer)
    twin = _clone(layer)
    twin.name = _unique_name(doc, layer.name + " copie")
    cmd = _call("Dupliquer le calque", lambda: siblings.insert(at + 1, twin), lambda: siblings.remove(twin))
    return twin, cmd


def set_props(layer: Layer, label: str = "Propriétés du calque", **changes):
    """Réglages d'un calque (nom, visible, opacité, mode, verrou, écrêtage, passthrough) : UNE étape."""
    before = {k: getattr(layer, k) for k in changes}
    for key, value in changes.items():
        if key not in Layer.PROPS:
            raise KeyError(key)
        if key == "blend" and value not in BLEND_MODES:
            raise ValueError(f"Mode de fusion inconnu : {value}")
    changes = dict(changes)
    if "opacity" in changes:
        changes["opacity"] = min(1.0, max(0.0, float(changes["opacity"])))

    def apply(values):
        for k, v in values.items():
            setattr(layer, k, v)
    return _call(label, lambda: apply(changes), lambda: apply(before))


def move_layer(doc, layer: Layer, parent: Layer | None, index: int):
    """Déplace le calque dans la pile (ordre, vers/depuis un groupe)."""
    if parent is not None and (parent is layer or layer in list(parent.walk())):
        raise ValueError("Un groupe ne peut pas entrer dans lui-même.")
    siblings, at = doc.parent_list(layer)
    target = parent.children if parent is not None else doc.layers

    def do():
        siblings.remove(layer)
        target.insert(max(0, min(index, len(target))), layer)

    def undo():
        target.remove(layer)
        siblings.insert(at, layer)
    return _call("Ordre des calques", do, undo)


def group_layers(doc, layers: list, name: str = "Groupe"):
    """Regroupe des calques FRÈRES (même liste) dans un nouveau groupe, à la place du plus haut."""
    layers = [l for l in layers]
    siblings, _ = doc.parent_list(layers[0])
    if any(doc.parent_list(l)[0] is not siblings for l in layers):
        raise ValueError("Les calques doivent avoir le même parent.")
    order = sorted(layers, key=lambda l: siblings.index(l))
    group = Layer(_unique_name(doc, name), "group")
    group.children = list(order)
    start = siblings.index(order[0])
    old = list(siblings)

    def do():
        for l in order:
            siblings.remove(l)
        siblings.insert(min(start, len(siblings)), group)
        group.children = list(order)

    def undo():
        siblings[:] = old
    return group, _call("Grouper les calques", do, undo)


def shift_layer(layer: Layer, sx: int, sy: int):
    """Déplace les pixels (et le masque) du calque de (sx, sy), sans étape d'annulation (geste en cours). La source d'un
    calque de texte ou de forme suit (sinon sa modification le ferait revenir à l'ancienne place)."""
    for node in layer.walk():
        if node.source:
            for kx, ky in (("x", "y"), ("x1", "y1")):
                if kx in node.source:
                    node.source[kx] = node.source[kx] + sx
                    node.source[ky] = node.source[ky] + sy
        if node.pix is not None and node.pix.data is not None:
            node.pix.shift(sx, sy)
        if node.mask is not None and node.mask.plane.data is not None:
            node.mask.plane.shift(sx, sy)


def translate_layer(layer: Layer, dx: int, dy: int):
    """Déplace le calque de (dx, dy) : rien n'est rééchantillonné."""
    return _call("Déplacer le calque", lambda: shift_layer(layer, dx, dy), lambda: shift_layer(layer, -dx, -dy))


def translation_done(layer: Layer, dx: int, dy: int, rect):
    """Étape d'annulation d'un déplacement DÉJÀ fait (geste interactif) ; `rect` = zone touchée."""
    return CallCommand("Déplacer le calque", lambda: shift_layer(layer, dx, dy),
                       lambda: shift_layer(layer, -dx, -dy), rect=rect)


def layer_rect(layer: Layer):
    """Zone couverte par les pixels du calque (ou de ses descendants)."""
    return _content_rect(layer)


# -- fusion --
def _content_rect(layer: Layer):
    rect = None
    for node in layer.walk():
        if node.pix is not None and node.pix.rect() is not None:
            rect = rect_union(rect, node.pix.rect())
    return rect


def merge_down(doc, layer: Layer):
    """Fusionne le calque avec celui du dessous (deux calques raster frères) ; le résultat garde le nom du dessous."""
    siblings, at = doc.parent_list(layer)
    if at <= 0:
        raise ValueError("Aucun calque en dessous.")
    below = siblings[at - 1]
    if below.is_group() or layer.is_group():
        raise ValueError("Fusion possible entre deux calques (pas de groupe) : fusionnez le groupe d'abord.")
    rect = rect_union(_content_rect(below), _content_rect(layer))
    old_pix = (below.pix.x, below.pix.y, None if below.pix.data is None else below.pix.data.copy())
    old_mask = below.mask
    old_props = below.props()
    if rect is None:
        merged = None
    else:
        probe = Layer("tmp")
        stack = [_shallow(below), _shallow(layer)]
        merged = C.to_straight_u8(C.compose(stack, rect))
        del probe

    def do():
        if merged is None:
            below.pix.clear()
        else:
            below.pix.set_all(rect[0], rect[1], merged)
        below.mask = None
        below.opacity, below.blend, below.clip = 1.0, "normal", below.clip
        siblings.remove(layer)

    def undo():
        siblings.insert(at, layer)
        x, y, data = old_pix
        if data is None:
            below.pix.clear()
        else:
            below.pix.set_all(x, y, data)
        below.mask = old_mask
        for k, v in old_props.items():
            setattr(below, k, v)
    return _call("Fusionner avec le calque inférieur", do, undo)


def _shallow(layer: Layer) -> Layer:
    """Vue du calque sans copier ses pixels (pour une composition temporaire)."""
    twin = Layer(layer.name, layer.kind)
    for key in Layer.PROPS:
        setattr(twin, key, getattr(layer, key))
    twin.pix, twin.mask, twin.children = layer.pix, layer.mask, layer.children
    return twin


def flatten(doc):
    """Aplatit toute la composition en UN calque (les calques cachés sont perdus, comme dans Photoshop)."""
    old = list(doc.layers)
    flat = Layer("Arrière-plan")
    flat.pix.set_all(0, 0, C.flatten_u8(doc))

    def do():
        doc.layers[:] = [flat]

    def undo():
        doc.layers[:] = old
    return flat, _call("Aplatir l'image", do, undo)


# -- masques --
def add_mask(layer: Layer, from_plane: Plane | None = None, hide_all: bool = False):
    if layer.mask is not None:
        raise ValueError("Le calque a déjà un masque.")
    mask = Mask(Plane(1, 0 if hide_all else 255))
    if from_plane is not None:
        mask.plane = from_plane
    return _call("Ajouter un masque", lambda: setattr(layer, "mask", mask), lambda: setattr(layer, "mask", None))


def remove_mask(layer: Layer):
    old = layer.mask
    if old is None:
        raise ValueError("Pas de masque.")
    return _call("Supprimer le masque", lambda: setattr(layer, "mask", None), lambda: setattr(layer, "mask", old))


def toggle_mask(layer: Layer, enabled: bool):
    mask = layer.mask
    before = mask.enabled
    return _call("Activer le masque" if enabled else "Désactiver le masque",
                 lambda: setattr(mask, "enabled", enabled), lambda: setattr(mask, "enabled", before))


def invert_mask(layer: Layer, doc_rect):
    mask = layer.mask
    old = (mask.plane.x, mask.plane.y, None if mask.plane.data is None else mask.plane.data.copy(), mask.plane.fill)
    plane = mask.plane
    rect = plane.rect()

    def do():
        plane.fill = 255 - plane.fill
        if plane.data is not None:
            plane.data = 255 - plane.data
        plane.rev += 1

    def undo():
        plane.x, plane.y, plane.data, plane.fill = old
        plane.rev += 1
    return _call("Inverser le masque", do, undo)


def apply_mask(layer: Layer, doc_rect):
    """Applique le masque aux pixels (alpha multiplié) puis le supprime."""
    mask = layer.mask
    if mask is None or layer.pix is None:
        raise ValueError("Rien à appliquer.")
    rect = layer.pix.rect()
    old = None if layer.pix.data is None else layer.pix.data.copy()
    ox, oy = layer.pix.x, layer.pix.y

    def do():
        if rect is not None and mask.enabled:
            factor = mask.plane.read(rect).astype(np.float32) / 255.0
            data = layer.pix.data.copy()
            data[..., 3] = np.clip(data[..., 3] * factor[..., 0] + 0.5, 0, 255)
            layer.pix.set_all(ox, oy, data)
        layer.mask = None

    def undo():
        layer.mask = mask
        if old is None:
            layer.pix.clear()
        else:
            layer.pix.set_all(ox, oy, old)
    return _call("Appliquer le masque", do, undo)


# -- pixels --
def replace_pixels(layer: Layer, rect, new: np.ndarray, label: str):
    """Remplace la zone `rect` des pixels du calque par `new` (étape de patch)."""
    before = layer.pix.read(rect)
    if np.array_equal(before, new):
        return None
    layer.pix.write(rect, new)
    return TilesCommand(label, layer, "pixels", [(tuple(rect), before, new.copy())])


def fill_rect(layer: Layer, rect, color: tuple, selection=None, label="Remplir"):
    """Remplit `rect` avec `color` (RGBA 0..255) en respectant la sélection (couverture partielle)."""
    rect = tuple(rect)
    before = layer.pix.read(rect)
    cover = np.ones(before.shape[:2], np.float32) if selection is None else selection.coverage(rect)
    alpha = cover * (color[3] / 255.0)
    old_a = before[..., 3].astype(np.float32) / 255.0
    new_a = alpha + old_a * (1.0 - alpha)
    weight = np.where(new_a > 1e-6, alpha / np.maximum(new_a, 1e-6), 0.0)[..., None]
    out = before.copy()
    out[..., :3] = np.clip(before[..., :3] * (1 - weight) + np.array(color[:3], np.float32) * weight + 0.5, 0, 255)
    out[..., 3] = np.clip(new_a * 255.0 + 0.5, 0, 255)
    return replace_pixels(layer, rect, out, label)


def compound(label, commands):
    commands = [c for c in commands if c is not None]
    return commands[0] if len(commands) == 1 else Compound(label, commands) if commands else None
