"""Module CAD du board : IMAGES et MASQUES — ATTACHER UNE IMAGE (IMAGEATTACH / IMAGE / IAT : image referencee,
`cad_image`), MASQUE (WIPEOUT / MASQUE / WI : hachure « wipeout » peinte de la couleur du fond par-dessus les traits).
Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

import os

from . import cad_hatch, cad_image
from . import cad_geometry as geo
from .cad_commands import Command, Prompt, UNDO_OPT

POLY_OPT = ("poly", "Polyligne", ("P", "POLYLIGNE", "POLYLINE"))


class ImageAttachCommand(Command):
    """ATTACHER UNE IMAGE (IMAGEATTACH / IMAGE / IAT) : le chemin du fichier (guillemets acceptes), le point
    d'insertion (coin bas gauche), la largeur (Entree = un pixel par unite du board), la rotation (Entree = 0)."""

    NAME = "IMAGEATTACH"
    LABEL = "Attacher une image"

    def start(self):
        self.path = None
        self.size = None                    # (largeur, hauteur) en pixels
        self.pos = None
        self.width = None

    def prompt(self):
        if self.path is None:
            return Prompt("Chemin du fichier image", [], "text")
        if self.pos is None:
            return Prompt("Spécifiez le point d'insertion (coin bas gauche)", [], "point")
        if self.width is None:
            return Prompt("Spécifiez la largeur de l'image", [], "point", self.pos,
                          self.ctx.fmt(self._default_width()), value="length")
        return Prompt("Spécifiez l'angle de rotation", [], "point", self.pos, "0", value="angle")

    def _default_width(self) -> float:
        return float(self.size[0]) if self.size else 100.0

    def typed(self, text: str):
        pass

    def text(self, raw: str):
        path = raw.strip().strip('"').strip("'")
        if not path:
            self.finish()
            return
        from .cad_items import picture
        image = picture(os.path.abspath(path)) if os.path.isfile(path) else None
        if image is None:
            self.ctx.message(f"Image « {path} » introuvable ou illisible.", error=True)
            return
        self.path = os.path.abspath(path)
        self.size = (image.width(), image.height())

    def click(self, p, raw: str):
        if raw.strip():
            self.text(raw)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.pos is None:
            self.pos = p
        elif self.width is None:
            d = geo.distance(self.pos, p)
            if d > geo.EPS:
                self.width = d
        else:
            self._make(geo.angle_deg(self.pos, p) if geo.distance(self.pos, p) > geo.EPS else 0.0)

    def value(self, number):
        if self.pos is None:
            return
        if self.width is None:
            if number <= 0:
                self.ctx.message("La largeur doit être > 0.", error=True)
                return
            self.width = number
        else:
            self._make(number)

    def enter(self):
        if self.path is None or self.pos is None:
            self.finish()
        elif self.width is None:
            self.width = self._default_width()
        else:
            self._make(0.0)

    def _fields(self, rot: float, width: float | None = None) -> dict:
        width = self.width if width is None else width
        height = width * self.size[1] / max(1, self.size[0])
        return cad_image.placed(self.path, self.pos, width, height, rot)

    def _make(self, rot: float):
        item = self.ctx.create_entity("cad_image", self._fields(rot % 360.0))
        self.ctx.commit_created([item], "Image")
        self.finish()

    def ghosts(self, p):
        if self.path is None or self.pos is None:
            return []
        width = self.width if self.width is not None else max(geo.EPS, geo.distance(self.pos, p))
        rot = geo.angle_deg(self.pos, p) if self.width is not None and geo.distance(self.pos, p) > geo.EPS else 0.0
        c = cad_image.corners(self._fields(rot, width))
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]


class WipeoutCommand(Command):
    """MASQUE (WIPEOUT / MASQUE / WI) : les sommets du contour (Entree = ferme, au moins 3), ou Polyligne (une polyligne
    fermee : son contour, la polyligne reste). Le masque cache ce qui est dessous ; les textes restent visibles."""

    NAME = "WIPEOUT"
    LABEL = "Masque"
    IMMEDIATE_PICK = True

    def start(self):
        self.points = []
        self.picking = False

    def prompt(self):
        if self.picking:
            return Prompt("Choisissez une polyligne fermée", [], "select")
        if not self.points:
            return Prompt("Spécifiez le premier point", [POLY_OPT], "point")
        return Prompt("Spécifiez le point suivant (Entrée = fermer)", [UNDO_OPT] if self.points else [], "point",
                      self.points[-1])

    def keyword(self, key):
        if key == "poly" and not self.points:
            self.picking = True
        elif key == "undo" and self.points:
            self.points.pop()

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.points and geo.distance(self.points[-1], p) <= geo.EPS:
            return
        self.points.append(p)

    def picked(self, items):
        for item in items:
            if item.kind == "cad_pline" and item.closed():
                pieces = __import__("fm_cad.cad_shapes", fromlist=["tessellate"]).tessellate(item.prims(),
                                                                                             self.ctx.tess_tol())
                loop = [p for piece in pieces for p in piece]
                self._make([list(p) for p in loop])
                return
            if item.kind == "cad_circle":
                pieces = __import__("fm_cad.cad_shapes", fromlist=["tessellate"]).tessellate(item.prims(),
                                                                                             self.ctx.tess_tol())
                self._make([list(p) for piece in pieces for p in piece])
                return
        self.ctx.message("Il faut une polyligne fermée (ou un cercle).", error=True)

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def enter(self):
        if len(self.points) >= 3:
            self._make([list(p) for p in self.points])
        else:
            if self.points:
                self.ctx.message("Il faut au moins 3 points : masque non créé.", error=True)
            self.finish()

    def _make(self, loop):
        loops = cad_hatch.clean_loops([loop])
        if not loops or abs(cad_hatch.signed_area(loops[0])) <= geo.EPS:
            self.ctx.message("Contour sans aire : masque non créé.", error=True)
            self.finish()
            return
        item = self.ctx.create_entity("cad_hatch", {"loops": loops, "hatch_pattern": cad_hatch.WIPEOUT,
                                                    "hatch_alpha": 100.0, "lineweight": 0.0})
        self.ctx.commit_created([item], "Masque")
        self.finish()

    def preview(self, p):
        if not self.points:
            return []
        pts = self.points + [(float(p[0]), float(p[1]))]
        out = [("rubber", a, b) for a, b in zip(pts, pts[1:])]
        if len(pts) >= 3:
            out.append(("rubber", pts[-1], pts[0]))
        return out


NEW_ENTRIES = (
    ("IMAGEATTACH", "Attacher une image", ("IAT", "IMAGE", "ATTACHERIMAGE", "IMAGEATTACHER"), ImageAttachCommand),
    ("WIPEOUT", "Masque", ("WI", "MASQUE", "NETTOYER"), WipeoutCommand),
)


def register(registry, entry_class, by_word):
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)


def _self_register():
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
