"""Aperçu d'un DÉPLACEMENT de calque (Qt) : pendant le glisser, la pile n'est pas recomposée à chaque évènement.

Mesure (4K, 24 calques) : recomposer toute la pile sous le calque déplacé coûtait ~1 s par évènement. Ici :
- le document SANS le calque déplacé est composé une fois par tuile touchée (`base_image`, cache pour le geste) ;
- le calque, converti UNE fois en image (masque appliqué), est dessiné par-dessus à son décalage courant avec son opacité
  et le mode de composition de Qt équivalent à son mode de fusion : aucun calcul NumPy par évènement ;
- les pixels du modèle ne bougent PAS pendant le geste : ils sont décalés à la fin (`Canvas.end_move`) et le cache de
  tuiles recompose alors le RÉSULTAT EXACT.
APPROXIMATION TEMPORAIRE, annoncée : l'aperçu pose le calque au-dessus de tout ce qui est situé au-dessus de lui dans la
pile (exact quand c'est le calque du dessus, sans groupe parent à opacité / mode / masque) et les modes de fusion sont
ceux de Qt (très proches des formules W3C). Elle disparaît au relâchement."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage, QPainter

from . import compose as C
from . import ops, render
from .planes import rect_intersect

TILE = render.TILE
MODES = {"normal": QPainter.CompositionMode_SourceOver, "multiply": QPainter.CompositionMode_Multiply,
         "screen": QPainter.CompositionMode_Screen, "overlay": QPainter.CompositionMode_Overlay,
         "softlight": QPainter.CompositionMode_SoftLight, "hardlight": QPainter.CompositionMode_HardLight,
         "darken": QPainter.CompositionMode_Darken, "lighten": QPainter.CompositionMode_Lighten,
         "difference": QPainter.CompositionMode_Difference, "exclusion": QPainter.CompositionMode_Exclusion,
         "add": QPainter.CompositionMode_Plus}


def _without(layers, target):
    """Copie de la liste des calques sans `target` (groupes recopiés, pixels partagés)."""
    out = []
    for layer in layers:
        if layer is target:
            continue
        if layer.children:
            clone = ops._shallow(layer)
            clone.children = _without(layer.children, target)
            out.append(clone)
        else:
            out.append(layer)
    return out


def _image_of(array: np.ndarray) -> tuple:
    array = np.ascontiguousarray(array)
    return array, QImage(array.data, array.shape[1], array.shape[0], array.shape[1] * 4,
                         QImage.Format_ARGB32_Premultiplied)


class MovePreview:
    def __init__(self, doc, layer):
        self.doc, self.layer = doc, layer
        self.rect = ops.layer_rect(layer)             # zone du calque au début du geste (repère du document)
        part = C._layer_part(layer, self.rect) if self.rect is not None else None
        self._keep = None
        self.layer_image = None
        if part is not None:
            self._keep, self.layer_image = _image_of(C.to_premult_u8(part[0]))
        self.layers_without = _without(doc.layers, layer)
        self.bases: dict = {}                         # (tx, ty) -> (tableau, QImage) : tuile SANS le calque
        self.touched: set = set()                     # tuiles que l'aperçu a pris en charge
        self.offset = (0, 0)

    def _tile_rect(self, key):
        return rect_intersect((key[0] * TILE, key[1] * TILE, key[0] * TILE + TILE, key[1] * TILE + TILE), self.doc.rect())

    def _mark(self, rect):
        clipped = rect_intersect(rect, self.doc.rect())
        if clipped is not None:
            for ty in range(clipped[1] // TILE, (clipped[3] - 1) // TILE + 1):
                for tx in range(clipped[0] // TILE, (clipped[2] - 1) // TILE + 1):
                    self.touched.add((tx, ty))

    def set_offset(self, dx: int, dy: int):
        """Nouveau décalage ; rend la zone du document à repeindre (ancienne ∪ nouvelle position)."""
        old = self.offset
        self.offset = (int(dx), int(dy))
        if self.rect is None:
            return None
        zones = [(self.rect[0] + o[0], self.rect[1] + o[1], self.rect[2] + o[0], self.rect[3] + o[1]) for o in (old, self.offset)]
        for z in zones:
            self._mark(z)
        return (min(z[0] for z in zones), min(z[1] for z in zones), max(z[2] for z in zones), max(z[3] for z in zones))

    def warm(self, visible):
        """Prépare au début du geste les tuiles situées sous le calque (et visibles) : ce petit délai initial évite de
        recalculer leur base pendant le glisser."""
        if self.rect is None:
            return
        zone = rect_intersect(self.rect, visible)
        if zone is None:
            return
        self._mark(zone)
        for key in list(self.touched):
            self.base_image(key)

    def base_image(self, key):
        """Tuile (QImage) du document sans le calque déplacé."""
        got = self.bases.get(key)
        if got is None:
            rect = self._tile_rect(key)
            if rect is None:
                return None
            got = self.bases[key] = _image_of(C.to_premult_u8(C.compose(self.layers_without, rect)))
        return got[1]

    def paint_layer(self, painter):
        """Pose le calque à son décalage courant (le peintre est en repère du document)."""
        if self.layer_image is None or self.rect is None:
            return
        painter.save()
        painter.setOpacity(painter.opacity() * self.layer.opacity)
        painter.setCompositionMode(MODES.get(self.layer.blend, QPainter.CompositionMode_SourceOver))
        painter.drawImage(self.rect[0] + self.offset[0], self.rect[1] + self.offset[1], self.layer_image)
        painter.restore()
