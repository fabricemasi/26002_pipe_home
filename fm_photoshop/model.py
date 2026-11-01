"""Modèle du document (SANS Qt) : document, calques, groupes, masques.

CONVENTIONS (voir docs/agents/fm_photoshop.md) :
- pixels des calques : RGBA 8 bits, couleurs encodées sRGB, alpha DROIT (non prémultiplié) ;
- composition en flottants prémultipliés (`compose.py`), dans l'espace encodé (comme Photoshop par défaut) ;
- le tableau d'un calque ne couvre que son contenu (`planes.Plane`), coordonnées du document, y vers le bas."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

from .planes import Plane

BLEND_MODES = ("normal", "multiply", "screen", "overlay", "softlight", "hardlight", "darken", "lighten",
               "difference", "exclusion", "add")
BLEND_LABELS = {"normal": "Normal", "multiply": "Produit", "screen": "Écran", "overlay": "Incrustation",
                "softlight": "Lumière tamisée", "hardlight": "Lumière forte", "darken": "Obscurcir",
                "lighten": "Éclaircir", "difference": "Différence", "exclusion": "Exclusion",
                "add": "Addition"}
MAX_SIDE = 30000                    # côté maximal d'un document (garde-fou)


def new_uid() -> str:
    return uuid.uuid4().hex[:16]


class Mask:
    __slots__ = ("plane", "enabled", "extra")

    def __init__(self, plane: Plane | None = None, enabled: bool = True):
        self.plane = plane or Plane(1, 255)         # hors du plan : 255 = calque visible
        self.enabled = enabled
        self.extra: dict = {}


class Layer:
    """Calque matriciel (`kind` = « raster ») ou groupe (« group », `children` du bas vers le haut)."""

    def __init__(self, name: str = "Calque", kind: str = "raster", uid: str | None = None):
        self.uid = uid or new_uid()
        self.name = name
        self.kind = kind
        self.visible = True
        self.opacity = 1.0
        self.blend = "normal"
        self.locked = False
        self.clip = False                           # masque d'écrêtage : limité à l'alpha du calque de base dessous
        self.passthrough = True                     # groupes : « passer à travers » (sinon isolé)
        self.pix = Plane(4, 0) if kind == "raster" else None
        self.mask: Mask | None = None
        self.children: list[Layer] = []
        self.extra: dict = {}                       # clés inconnues (versions plus récentes), réécrites telles quelles

    def is_group(self) -> bool:
        return self.kind == "group"

    def walk(self):
        """Ce calque puis ses descendants (profondeur d'abord, bas -> haut)."""
        yield self
        for child in self.children:
            yield from child.walk()

    PROPS = ("name", "visible", "opacity", "blend", "locked", "clip", "passthrough")

    def props(self) -> dict:
        return {k: getattr(self, k) for k in self.PROPS}

    def nbytes(self) -> int:
        total = self.pix.nbytes() if self.pix is not None else 0
        if self.mask is not None:
            total += self.mask.plane.nbytes()
        return total


@dataclass
class Document:
    width: int
    height: int
    name: str = "Sans titre"
    dpi: float = 72.0
    layers: list = field(default_factory=list)      # niveau supérieur, du bas vers le haut
    icc_name: str = "sRGB"
    icc_profile: bytes | None = None
    depth: int = 8
    meta: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    uid: str = field(default_factory=new_uid)

    def rect(self):
        return (0, 0, self.width, self.height)

    def walk(self):
        for layer in self.layers:
            yield from layer.walk()

    def find(self, uid: str):
        for layer in self.walk():
            if layer.uid == uid:
                return layer
        return None

    def parent_list(self, layer: Layer):
        """(liste contenante, indice) du calque, ou (None, -1)."""
        def search(items):
            for i, item in enumerate(items):
                if item is layer:
                    return items, i
                if item.children:
                    found = search(item.children)
                    if found[0] is not None:
                        return found
            return None, -1
        return search(self.layers)

    def parent_of(self, layer: Layer):
        """Groupe parent (None = niveau supérieur)."""
        def search(items, parent):
            for item in items:
                if item is layer:
                    return True, parent
                if item.children:
                    ok, found = search(item.children, item)
                    if ok:
                        return True, found
            return False, None
        return search(self.layers, None)[1]

    def nbytes(self) -> int:
        return sum(layer.nbytes() for layer in self.walk())


def new_document(width: int, height: int, name: str = "Sans titre", dpi: float = 72.0,
                 background: tuple | None = (255, 255, 255, 255)) -> Document:
    """Document neuf : un calque « Arrière-plan » plein (couleur RGBA) ou, sans fond, un calque transparent."""
    width, height = int(width), int(height)
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise ValueError(f"Dimensions invalides : {width} × {height} (1 à {MAX_SIDE} pixels).")
    doc = Document(width, height, name=name, dpi=float(dpi))
    if background is None:
        doc.layers.append(Layer("Calque 1"))
    else:
        layer = Layer("Arrière-plan")
        layer.pix.set_all(0, 0, np.broadcast_to(np.array(background, np.uint8), (height, width, 4)).copy())
        doc.layers.append(layer)
    return doc
