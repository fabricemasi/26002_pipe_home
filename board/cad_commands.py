"""Module CAD du board : COMMANDES interactives et leur registre (aucun widget).

Une commande se lance de la meme facon depuis la barre d'outils, la barre de commande ou un raccourci : par
son nom dans le REGISTRE (`REGISTRY`, alias compris) — une seule implementation, un seul etat. Le controleur
(`cad.CadController`) lui transmet les points DEJA RESOLUS par le moteur d'accrochage (clic, coordonnees
saisies, distance directe), les options choisies et Entree / Echap ; la commande decrit son invite
(`prompt()` : texte, options, point de base pour l'elastique, l'ORTHO, le suivi polaire, la saisie relative)
et sa previsualisation (`preview(point)` : traits TEMPORAIRES, jamais d'entite creee au mouvement du curseur).

Annulation : une commande complete = UNE etape (LIGNE : tous ses segments ; l'option annUler de la commande
retire le dernier segment, comme AutoCAD). Les entites creees en cours de commande sont dans la scene mais
pas encore dans l'annulation (`ctx.commit_created` a la fin, y compris sur Echap qui GARDE les segments deja
faits, comme AutoCAD).

Commandes disponibles : LIGNE, POLYLIGNE, CERCLE, ARC, DEPLACER, COPIER, EFFACER, DECALER, CHANFREIN, RACCORD,
PIPETTE (MATCHPROP), TEXTE, TEXTE MULTILIGNE, MODIFIER UN TEXTE, DECOMPOSER, CALQUE, PROPRIETES, ACCROBJ / DSETTINGS,
U, RETABLIR, ORTHO, GRILLE, RESOL, AIDE. Les commandes des phases suivantes sont DECLAREES (`PLANNED`) : les
taper donne un message clair, elles ne sont jamais proposees comme disponibles."""
from __future__ import annotations

from dataclasses import dataclass, field

import math

from . import cad_geometry as geo
from . import cad_dims, cad_hatch, cad_input, cad_shapes, cad_text, cad_tools, cad_trim


@dataclass
class Prompt:
    text: str
    options: list = field(default_factory=list)   # [(cle, libelle a capitales, (mots acceptes…))]
    kind: str = "point"                             # point | select | enter | text (saisie libre d'un texte)
    base: tuple | None = None                       # point de base (elastique, ortho, polaire, relatif)
    default: str = ""                               # valeur proposee (Entree)
    value: str = ""                                 # invite de valeur : "length" (unite du dessin) | "angle"

    def line(self) -> str:
        text = self.text
        if self.options:
            text += " ou [" + "/".join(label for _k, label, _w in self.options) + "]"
        if self.default:
            text += f" <{self.default}>"
        return text + " :"


UNDO_OPT = ("undo", "annUler", ("UNDO", "U", "ANNULER"))
CLOSE_OPT = ("close", "Clore", ("CLOSE", "C", "CLORE"))
EXIT_OPT = ("exit", "Quitter", ("EXIT", "X", "QUITTER", "Q"))


class Command:
    """Base des commandes interactives. `ctx` = le controleur CAD (voir cad.CadController)."""

    NAME = ""
    LABEL = ""
    REPEATABLE = True

    def __init__(self, ctx):
        self.ctx = ctx
        self.finished = False

    def start(self):
        pass

    def prompt(self) -> Prompt:
        return Prompt("")

    def point(self, p):
        pass

    def keyword(self, key: str):
        pass

    def value(self, number: float):
        """Valeur tapee a une invite de valeur (`Prompt.value`) : longueur en unites du board, ou degres."""

    def enter(self):
        self.finish()

    def cancel(self):
        self.finish()

    def selection_done(self, items):
        pass

    def preview(self, p) -> list:
        """Traits temporaires [(sorte, a, b)] (document) pour la position resolue `p` du curseur."""
        return []

    def ghosts(self, p) -> list:
        """Entites fantomes [(a, b)] (document) : apercu de ce que la commande produira."""
        return []

    def finish(self):
        self.finished = True


# ==========================================================================
# LIGNE (LINE) — reproduit la commande d'AutoCAD
# ==========================================================================

class LineCommand(Command):
    NAME = "LINE"
    LABEL = "Ligne"

    def start(self):
        self.first = None              # premier point de la sequence (option Clore)
        self.last = None               # dernier point valide
        self.segments = []             # entites creees par CETTE commande (ordre)
        self.starts = []               # point de depart de chaque segment (annUler)

    def prompt(self):
        if self.last is None:
            default = "continuer" if self.ctx.last_line_end is not None else ""
            return Prompt("Spécifiez le premier point", [], "point", None, default)
        options = [CLOSE_OPT, UNDO_OPT] if len(self.segments) >= 2 else [UNDO_OPT]
        return Prompt("Spécifiez le point suivant", options, "point", self.last)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.last is None:
            self.first = self.last = p
            return
        if geo.distance(self.last, p) <= geo.EPS:
            self.ctx.message("Point identique au précédent : segment de longueur nulle ignoré.", error=True)
            return
        item = self.ctx.create_line(self.last, p)
        if item is None:
            return
        self.segments.append(item)
        self.starts.append(self.last)
        self.last = p
        self.ctx.last_line_end = p

    def keyword(self, key):
        if key == "undo":
            if not self.segments:
                self.first = self.last = None
                self.ctx.message("Tout a été annulé.")
                return
            item = self.segments.pop()
            self.last = self.starts.pop()
            self.ctx.remove_uncommitted(item)
            self.ctx.last_line_end = self.last
            if not self.segments:
                self.first = self.last
        elif key == "close":
            if len(self.segments) < 2 or self.first is None:
                self.ctx.message("Il faut au moins deux segments pour clore.", error=True)
                return
            self.point(self.first)
            self.finish()

    def enter(self):
        if self.last is None and self.ctx.last_line_end is not None:
            self.first = self.last = self.ctx.last_line_end        # reprise a la derniere extremite
            return
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.commit_created(self.segments, "Ligne" if len(self.segments) <= 1
                                    else f"Ligne ({len(self.segments)} segments)")
        super().finish()

    def preview(self, p):
        return [("rubber", self.last, p)] if self.last is not None else []


# ==========================================================================
# Selection d'objets (sous-etape commune : EFFACER, DEPLACER, COPIER)
# ==========================================================================

class _SelectingCommand(Command):
    """Prend la selection courante (nom puis verbe) ; sinon demande « Choix des objets » (clic, fenetre,
    capture ; Entree termine), comme AutoCAD."""

    EDITS = True

    def start(self):
        items = self.ctx.selection()
        self.items = None
        if items:
            self._take(items)
        if self.items is None:
            self.ctx.begin_object_selection()

    def _take(self, items):
        if self.EDITS:
            items = self.ctx.editable(items)
        if items:
            self.items = items
            self.after_selection()
        else:
            self.ctx.message("Aucun objet modifiable sélectionné.", error=True)

    def selection_done(self, items):
        if not items:
            self.ctx.message("Aucun objet choisi : commande terminée.")
            self.finish()
            return
        self._take(items)
        if self.items is None:
            self.finish()

    def prompt(self):
        if self.items is None:
            return Prompt("Choix des objets", [], "select")
        return self.step_prompt()

    def after_selection(self):
        pass

    def step_prompt(self) -> Prompt:
        return Prompt("")


class EraseCommand(_SelectingCommand):
    NAME = "ERASE"
    LABEL = "Effacer"

    def after_selection(self):
        self.ctx.delete(self.items)
        self.finish()


class MoveCommand(_SelectingCommand):
    NAME = "MOVE"
    LABEL = "Déplacer"
    COPY = False

    def after_selection(self):
        self.base = None
        self.created = []
        self.ctx.highlight(self.items)

    def step_prompt(self):
        if self.base is None:
            return Prompt("Spécifiez le point de base", [("disp", "Déplacement", ("DISPLACEMENT", "D"))],
                          "point", None, "Déplacement")
        options = [UNDO_OPT, EXIT_OPT] if (self.COPY and self.created) else ([EXIT_OPT] if self.COPY else [])
        default = "quitter" if self.COPY else "utiliser le premier point comme déplacement"
        return Prompt("Spécifiez le deuxième point", options, "point", self.base, default)

    def point(self, p):
        if self.items is None:
            return
        if self.base is None:
            self.base = (float(p[0]), float(p[1]))
            return
        self._apply(geo.sub(p, self.base))

    def _apply(self, delta):
        if self.COPY:
            self.created.append(self.ctx.copy_items(self.items, delta))
            return
        self.ctx.translate(self.items, delta, "Déplacer")
        self.finish()

    def keyword(self, key):
        if key == "disp" and self.base is None:
            self.base = (0.0, 0.0)          # le point suivant est lu comme un deplacement depuis l'origine
            self.ctx.message("Spécifiez le déplacement (x,y) : le point suivant est lu depuis l'origine.")
        elif key == "undo" and self.COPY and self.created:
            for item in self.created.pop():
                self.ctx.remove_uncommitted(item)
        elif key == "exit":
            self.finish()

    def enter(self):
        if self.items is not None and self.base is not None and not self.COPY:
            self._apply(self.base)            # Entree : le premier point est le deplacement (AutoCAD)
            return
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
            if self.COPY:
                items = [i for group in getattr(self, "created", []) for i in group]
                self.ctx.commit_created(items, "Copier", select=False)
        super().finish()

    def ghosts(self, p):
        if self.items is None or self.base is None:
            return []
        delta = geo.sub(p, self.base)
        return [(geo.add(a, delta), geo.add(b, delta)) for item in self.items for a, b in item.outline(self.ctx.tess_tol())]

    def preview(self, p):
        return [("rubber", self.base, p)] if (self.items is not None and self.base is not None) else []


class CopyCommand(MoveCommand):
    NAME = "COPY"
    LABEL = "Copier"
    COPY = True


# ==========================================================================
# PIPETTE (MATCHPROP) : copier les proprietes d'un objet sur d'autres
# ==========================================================================

class MatchPropCommand(Command):
    """Comme CORRESPROP / MATCHPROP d'AutoCAD : un objet SOURCE (la selection s'il y en a une seule, sinon un clic),
    puis chaque objet de destination choisi (clic ou fenetre) recoit TOUTES ses proprietes (calque, couleur,
    epaisseur, type de ligne et son echelle, terminaisons, repartition — overrides compris, valeurs « ByLayer » /
    « selon le type » comprises) ; une etape d'annulation par choix. Entree / Echap : fin."""

    NAME = "MATCHPROP"
    LABEL = "Pipette"
    IMMEDIATE_PICK = True          # le controleur transmet chaque choix aussitot (`picked`)

    def start(self):
        selection = self.ctx.selection()
        self.source = selection[0] if len(selection) == 1 else None
        self.count = 0
        self.ctx.scene.clearSelection()
        if self.source is not None:
            self.ctx.highlight([self.source])

    def prompt(self):
        if self.source is None:
            return Prompt("Choisissez l'objet source", [], "select")
        return Prompt("Choisissez les objets de destination", [], "select")

    def picked(self, items):
        if self.source is None:
            self.source = items[0]
            self.ctx.highlight([self.source])
            self.ctx.message("Objet source choisi : cliquez les objets à modifier (Entrée pour terminer).")
            return
        targets = [i for i in items if i is not self.source]
        self.count += self.ctx.match_properties(self.source, targets)

    def selection_done(self, items):
        if items:
            self.picked(items)
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
            if self.count:
                self.ctx.message(f"Pipette : {self.count} objet(s) modifié(s).")
        super().finish()


# ==========================================================================
# Poignees (grips) : ETIREMENT d'une extremite / DEPLACEMENT par le milieu
# ==========================================================================

class GripCommand(Command):
    """Lancee par un clic sur une poignee chaude (pas par son nom). Les extremites de TOUTES les lignes
    selectionnees placees au meme point suivent (comme les grips d'AutoCAD). Entree : mode suivant
    (ETIREMENT <-> DEPLACEMENT) ; Copier : laisse les originaux et cree des copies."""

    NAME = "GRIP"
    LABEL = "Poignée"
    REPEATABLE = False

    def __init__(self, ctx, grips, base, mode: str):
        super().__init__(ctx)
        self.grips = grips              # [(item, "p1" | "p2" | "mid")]
        self.base = base
        self.mode = mode                # stretch | move
        self.copy = False
        self.created = []

    def items(self):
        out = []
        for item, _g in self.grips:
            if item not in out:
                out.append(item)
        return out

    def prompt(self):
        title = "** ÉTIREMENT **" if self.mode == "stretch" else "** DÉPLACEMENT **"
        point = "le point d'étirement" if self.mode == "stretch" else "le point de déplacement"
        options = [("copy", "Copier", ("COPY", "C", "COPIER")), EXIT_OPT]
        if self.copy and self.created:
            options.insert(0, UNDO_OPT)
        return Prompt(f"{title} Spécifiez {point}", options, "point", self.base)

    def _changes(self, p):
        """[(element, nouveaux champs geometriques ou None si degenere)] pour la position `p`."""
        delta = geo.sub(p, self.base)
        out = []
        for item in self.items():
            names = {g for i, g in self.grips if i is item}
            out.append((item, cad_shapes.grip_edit(item.kind, item.geometry(), names, delta, self.mode == "move")))
        return out

    def point(self, p):
        changes = self._changes(p)
        if any(g is None for _i, g in changes):
            self.ctx.message("Un objet deviendrait dégénéré (longueur ou rayon nul, points alignés) : point refusé.",
                             error=True)
            return
        if self.copy:
            self.created.append(self.ctx.create_copies(changes))
            return
        self.ctx.set_geometry(changes, "Étirer" if self.mode == "stretch" else "Déplacer")
        self.finish()

    def keyword(self, key):
        if key == "copy":
            self.copy = True
        elif key == "undo" and self.created:
            for item in self.created.pop():
                self.ctx.remove_uncommitted(item)
        elif key == "exit":
            self.finish()

    def enter(self):
        if self.copy:
            self.finish()
            return
        self.mode = "move" if self.mode == "stretch" else "stretch"

    def finish(self):
        if not self.finished and self.created:
            self.ctx.commit_created([i for group in self.created for i in group], "Copier (poignée)",
                                    select=False)
        super().finish()

    def ghosts(self, p):
        tol = self.ctx.tess_tol()
        return [seg for item, g in self._changes(p) if g is not None
                for seg in cad_shapes.display_segments(cad_shapes.prims(item.kind, {**item.geometry(), **g}), tol)]

    def preview(self, p):
        return [("rubber", self.base, p)]


# ==========================================================================
# CERCLE, ARC, POLYLIGNE (dessin)
# ==========================================================================

def _show(ctx, kind: str, data: dict) -> list:
    """Traits d'apercu [(sorte, a, b)] d'une entite pas encore creee."""
    return [("rubber", a, b) for a, b in cad_shapes.display_segments(cad_shapes.prims(kind, data), ctx.tess_tol())]


class CircleCommand(Command):
    """CERCLE (C) : centre puis rayon (ou Diametre) ; options 3P (trois points) et 2P (diametre par deux points)."""

    NAME = "CIRCLE"
    LABEL = "Cercle"

    def start(self):
        self.mode = "center"
        self.center = None
        self.diameter = False
        self.points = []

    def prompt(self):
        if self.mode == "center":
            if self.center is None:
                return Prompt("Spécifiez le centre du cercle", [("3p", "3P", ("3P",)), ("2p", "2P", ("2P",))], "point")
            if self.diameter:
                return Prompt("Spécifiez le diamètre du cercle", [], "point", self.center, value="length")
            return Prompt("Spécifiez le rayon du cercle", [("diam", "Diamètre", ("D", "DIAMETRE", "DIAMÈTRE",
                                                                                  "DIAMETER"))],
                          "point", self.center, value="length")
        names = ("premier", "deuxième", "troisième") if self.mode == "3p" else ("première extrémité du",
                                                                                 "deuxième extrémité du")
        n = len(self.points)
        text = (f"Spécifiez le {names[n]} point du cercle" if self.mode == "3p"
                else f"Spécifiez la {names[n]} diamètre")
        return Prompt(text, [], "point", self.points[-1] if self.points else None)

    def keyword(self, key):
        if key in ("3p", "2p") and self.center is None:
            self.mode = key
        elif key == "diam":
            self.diameter = True

    def _circle(self, p):
        if self.mode == "center" and self.center is not None:
            r = geo.distance(self.center, p) / (2.0 if self.diameter else 1.0)
            return self.center, r
        if self.mode == "2p" and len(self.points) == 1:
            return geo.midpoint(self.points[0], p), geo.distance(self.points[0], p) / 2.0
        if self.mode == "3p" and len(self.points) == 2:
            found = cad_shapes.arc_from_3_points(self.points[0], self.points[1], p)
            return (found[0], found[1]) if found else None
        return None

    def point(self, p):
        if self.mode == "center" and self.center is None:
            self.center = (float(p[0]), float(p[1]))
            return
        if self.mode != "center" and len(self.points) < (1 if self.mode == "2p" else 2):
            self.points.append((float(p[0]), float(p[1])))
            return
        found = self._circle(p)
        if found is None:
            self.ctx.message("Points alignés : aucun cercle ne passe par eux.", error=True)
            return
        self._make(*found)

    def value(self, number):
        if self.mode == "center" and self.center is not None:
            self._make(self.center, number / (2.0 if self.diameter else 1.0))
        else:
            self.ctx.message("Un point est attendu ici.", error=True)

    def _make(self, c, r):
        if r <= geo.EPS:
            self.ctx.message("Rayon nul : cercle refusé.", error=True)
            return
        item = self.ctx.create_entity("cad_circle", {"center": [c[0], c[1]], "radius": r})
        self.ctx.commit_created([item], "Cercle")
        self.finish()

    def preview(self, p):
        found = self._circle(p)
        out = []
        if self.mode == "center" and self.center is not None:
            out.append(("rubber", self.center, p))
        if found is not None and found[1] > geo.EPS:
            out += _show(self.ctx, "cad_circle", {"center": list(found[0]), "radius": found[1]})
        return out


class ArcCommand(Command):
    """ARC (A) : trois points (depart, point de l'arc, extremite), ou Centre puis depart puis extremite (sens
    trigonometrique, comme AutoCAD)."""

    NAME = "ARC"
    LABEL = "Arc"

    def start(self):
        self.points = []
        self.center = None
        self.center_mode = False

    def prompt(self):
        n = len(self.points)
        if self.center_mode:
            if self.center is None:
                return Prompt("Spécifiez le centre de l'arc", [], "point")
            if n == 0:
                return Prompt("Spécifiez le point de départ de l'arc", [], "point", self.center)
            return Prompt("Spécifiez l'extrémité de l'arc (sens trigonométrique)", [], "point", self.center)
        if n == 0:
            return Prompt("Spécifiez le point de départ de l'arc", [("center", "Centre", ("C", "CE", "CENTRE",
                                                                                         "CENTER"))], "point")
        if n == 1:
            return Prompt("Spécifiez le deuxième point de l'arc", [], "point", self.points[0])
        return Prompt("Spécifiez l'extrémité de l'arc", [], "point", self.points[1])

    def keyword(self, key):
        if key == "center" and not self.points:
            self.center_mode = True

    def _arc(self, p):
        if self.center_mode and self.center is not None and len(self.points) == 1:
            start = self.points[0]
            r = geo.distance(self.center, start)
            if r <= geo.EPS:
                return None
            return {"center": list(self.center), "radius": r, "start": geo.angle_deg(self.center, start),
                    "end": geo.angle_deg(self.center, p)}
        if not self.center_mode and len(self.points) == 2:
            found = cad_shapes.arc_from_3_points(self.points[0], self.points[1], p)
            return cad_shapes.arc_data(*found) if found else None
        return None

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.center_mode and self.center is None:
            self.center = p
            return
        if len(self.points) < (1 if self.center_mode else 2):
            if self.points and geo.distance(self.points[-1], p) <= geo.EPS:
                self.ctx.message("Point identique au précédent.", error=True)
                return
            self.points.append(p)
            return
        data = self._arc(p)
        if data is None:
            self.ctx.message("Points alignés ou confondus : aucun arc possible.", error=True)
            return
        item = self.ctx.create_entity("cad_arc", data)
        self.ctx.commit_created([item], "Arc")
        self.finish()

    def preview(self, p):
        data = self._arc(p)
        base = self.center if self.center_mode else (self.points[-1] if self.points else None)
        out = [("rubber", base, p)] if base is not None else []
        return out + (_show(self.ctx, "cad_arc", data) if data else [])


class PlineCommand(Command):
    """POLYLIGNE (PL) : sommets successifs, segments droits ou en Arc (arc TANGENT au segment precedent, comme
    AutoCAD) ; Clore, annUler ; Entree / Echap = fin (la polyligne est creee en une etape d'annulation)."""

    NAME = "PLINE"
    LABEL = "Polyligne"

    def start(self):
        self.verts = []
        self.arc = False
        self.closed = False

    def prompt(self):
        if not self.verts:
            return Prompt("Spécifiez le point de départ", [], "point")
        options = [("line", "Ligne", ("L", "LIGNE", "LINE")) if self.arc else ("arc", "Arc", ("A", "ARC"))]
        if len(self.verts) >= 3:
            options.append(CLOSE_OPT)
        options.append(UNDO_OPT)
        text = "Spécifiez l'extrémité de l'arc" if self.arc else "Spécifiez le point suivant"
        last = self.verts[-1]
        return Prompt(text, options, "point", (last[0], last[1]))

    def _tangent(self):
        if len(self.verts) < 2:
            return (1.0, 0.0)
        a, b = self.verts[-2], self.verts[-1]
        seg = cad_shapes.bulge_arc((a[0], a[1]), (b[0], b[1]), a[2])
        return cad_shapes.prim_tangent(seg, cad_shapes.prim_length(seg))

    def _bulge(self, p) -> float:
        if not self.arc:
            return 0.0
        last = (self.verts[-1][0], self.verts[-1][1])
        t = self._tangent()
        chord = geo.sub(p, last)
        beta = math.atan2(geo.cross(t, chord), geo.dot(t, chord))
        if abs(abs(beta) - math.pi) <= 1e-6:
            return 0.0
        return math.tan(beta / 2.0)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.verts and geo.distance((self.verts[-1][0], self.verts[-1][1]), p) <= geo.EPS:
            self.ctx.message("Point identique au précédent : ignoré.", error=True)
            return
        if self.verts:
            self.verts[-1][2] = self._bulge(p)
        self.verts.append([p[0], p[1], 0.0])

    def keyword(self, key):
        if key == "arc":
            self.arc = True
        elif key == "line":
            self.arc = False
        elif key == "undo" and self.verts:
            self.verts.pop()
            if self.verts:
                self.verts[-1][2] = 0.0
        elif key == "close" and len(self.verts) >= 3:
            first = (self.verts[0][0], self.verts[0][1])
            self.verts[-1][2] = self._bulge(first)
            self.closed = True
            self.finish()

    def finish(self):
        if not self.finished and len(self.verts) >= 2:
            item = self.ctx.create_entity("cad_pline", {"vertices": [list(v) for v in self.verts],
                                                        "closed": self.closed})
            self.ctx.commit_created([item], "Polyligne")
        super().finish()

    def preview(self, p):
        if not self.verts:
            return []
        out = _show(self.ctx, "cad_pline", {"vertices": self.verts, "closed": False}) if len(self.verts) > 1 else []
        last = (self.verts[-1][0], self.verts[-1][1])
        out += _show(self.ctx, "cad_pline", {"vertices": [[last[0], last[1], self._bulge(p)], [p[0], p[1], 0.0]]})
        return out


# ==========================================================================
# DECALER (OFFSET)
# ==========================================================================

class OffsetCommand(Command):
    """DECALER (O) : distance (memorisee d'une fois a l'autre) ou Par (passant par un point) ; puis, en boucle,
    l'objet a decaler et le cote (apercu au survol) ; chaque decalage = une etape d'annulation ; annUler retire le
    dernier ; Entree / Echap = fin. Lignes, arcs, cercles, polylignes (sommets raccordes)."""

    NAME = "OFFSET"
    LABEL = "Décaler"
    IMMEDIATE_PICK = True

    def start(self):
        memory = self.ctx.tool_memory
        self.distance = memory.get("offset")
        self.through = memory.get("offset") == "through"
        if self.through:
            self.distance = None
        self.asking = True
        self.first = None                   # 1er point d'une distance donnee par deux points
        self.target = None
        self.count = 0
        self.ctx.scene.clearSelection()

    def _default(self) -> str:
        if self.through:
            return "Par"
        return self.ctx.fmt(self.distance) if self.distance else ""

    def prompt(self):
        if self.asking:
            if self.first is not None:
                return Prompt("Spécifiez le deuxième point", [], "point", self.first, value="length")
            return Prompt("Spécifiez la distance de décalage", [("through", "Par", ("P", "PAR", "T", "THROUGH"))],
                          "point", None, self._default(), value="length")
        if self.target is None:
            options = [EXIT_OPT] + ([UNDO_OPT] if self.count else [])
            return Prompt("Choisissez l'objet à décaler", options, "select", None, "Quitter")
        if self.through:
            return Prompt("Spécifiez le point de passage", [EXIT_OPT], "point")
        return Prompt("Spécifiez un point du côté à décaler", [EXIT_OPT], "point")

    def value(self, number):
        if number <= geo.EPS:
            self.ctx.message("La distance doit être positive.", error=True)
            return
        self.distance = number
        self.through = False
        self.ctx.tool_memory["offset"] = number
        self.asking = False
        self.first = None

    def keyword(self, key):
        if key == "through" and self.asking:
            self.through = True
            self.ctx.tool_memory["offset"] = "through"
            self.asking = False
        elif key == "exit":
            self.finish()
        elif key == "undo" and self.count:
            self.ctx.pane.undo()
            self.count -= 1

    def enter(self):
        if self.asking:
            if self.through or self.distance:
                self.asking = False                 # valeur memorisee
                return
            self.ctx.message("Donnez une distance (ou Par).", error=True)
            return
        if self.target is not None:
            self.target = None
            return
        self.finish()

    def picked(self, items):
        if self.asking or not items:
            return
        self.target = items[0]
        self.ctx.scene.clearSelection()
        self.ctx.highlight([self.target])

    def selection_done(self, items):
        if items:
            self.picked(items)
            return
        self.finish()

    def _result(self, item, p):
        distance = cad_tools.through_distance(item.kind, item.geometry(), p) if self.through else self.distance
        if not distance:
            return "Distance nulle : le point est sur l'objet."
        return cad_tools.offset_entity(item.kind, item.geometry(), distance, p)

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.asking:
            if self.first is None:
                self.first = p
                return
            self.value(geo.distance(self.first, p))
            return
        if self.target is None:
            return
        result = self._result(self.target, p)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        kind, geometry = result
        self.ctx.apply_edit([], [(kind, geometry, self.target)], "Décaler")
        self.count += 1
        self.target = None
        self.ctx.highlight([])

    def ghosts(self, p):
        if self.target is None:
            return []
        result = self._result(self.target, p)
        if isinstance(result, str):
            return []
        kind, geometry = result
        return cad_shapes.display_segments(cad_shapes.prims(kind, geometry), self.ctx.tess_tol())

    def hover_ghosts(self, item, cursor):
        if item is None or self.through or not self.distance or self.target is not None:
            return []
        return self.ghosts_for(item, cursor)

    def ghosts_for(self, item, cursor):
        result = cad_tools.offset_entity(item.kind, item.geometry(), self.distance, cursor)
        if isinstance(result, str):
            return []
        return cad_shapes.display_segments(cad_shapes.prims(*result), self.ctx.tess_tol())

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
            if self.count:
                self.ctx.message(f"Décaler : {self.count} objet(s) créé(s).")
        super().finish()


# ==========================================================================
# CHANFREIN (CHAMFER) et RACCORD (FILLET)
# ==========================================================================

TRIM_OPT = ("trim", "Ajuster", ("A", "AJ", "AJUSTER", "T", "TRIM"))
POLY_OPT = ("poly", "Polyligne", ("P", "PO", "POLYLIGNE", "POLYLINE"))
MULTI_OPT = ("multiple", "Multiple", ("M", "MU", "MULTIPLE"))


class _CornerCommand(Command):
    """Base de CHANFREIN et RACCORD : deux objets choisis (le cote garde = celui du clic, comme AutoCAD), apercu au
    survol du second, une etape d'annulation par coin ; options memorisees (`ctx.tool_memory`)."""

    IMMEDIATE_PICK = True
    TOOL = ""

    def start(self):
        self.first = None                   # (element, point clique)
        self.ask = None                     # valeur demandee : (cle de memoire, texte, sorte) ; file `self.asks`
        self.asks = []
        self.choice = None                  # choix d'option demande (Ajuster / Methode)
        self.poly = False
        self.multiple = False
        self.done = 0
        self.ctx.scene.clearSelection()
        self.ctx.message(self.status())

    # -- invites --
    def status(self) -> str:
        return ""

    def first_options(self) -> list:
        return []

    def prompt(self):
        memory = self.ctx.tool_memory
        if self.ask is not None:
            key, text, kind = self.ask
            current = memory[key]
            default = self.ctx.fmt(current) if kind == "length" else f"{current:g}"
            return Prompt(text, [], "point", None, default, value=kind)
        if self.choice == "trim":
            return Prompt("Mode Ajuster", [("yes", "Ajuster", ("A", "AJUSTER", "T", "TRIM")),
                                           ("no", "Non ajuster", ("N", "NON", "NO", "NOTRIM"))], "point", None,
                          "Ajuster" if memory["trim"] else "Non ajuster")
        if self.choice == "method":
            return Prompt("Méthode", [("distance", "Distance", ("D", "DISTANCE")), ("angle", "Angle", ("A", "ANGLE"))],
                          "point", None, "Distance" if memory["chamfer_method"] == "distance" else "Angle")
        if self.poly:
            return Prompt("Choisissez la polyligne", [], "select")
        if self.first is None:
            return Prompt(self.FIRST_TEXT, self.first_options(), "select")
        return Prompt(self.SECOND_TEXT, [], "select")

    def _ask(self, *asks):
        self.asks = list(asks)
        self.ask = self.asks.pop(0) if self.asks else None

    def value(self, number):
        if self.ask is None:
            return
        key, _text, kind = self.ask
        if number < 0 or (kind == "angle" and not 0 < number < 180):
            self.ctx.message("Valeur hors limites.", error=True)
            return
        self.ctx.tool_memory[key] = float(number)
        self.ask = self.asks.pop(0) if self.asks else None
        if self.ask is None:
            self.ctx.message(self.status())

    def point(self, p):
        if self.ask is not None or self.choice is not None:
            self.ctx.message("Une valeur ou une option est attendue.", error=True)

    def enter(self):
        if self.ask is not None:                    # Entree : valeur proposee gardee
            self.ask = self.asks.pop(0) if self.asks else None
            if self.ask is None:
                self.ctx.message(self.status())
            return
        if self.choice is not None:
            self.choice = None
            return
        self.finish()

    def keyword(self, key):
        memory = self.ctx.tool_memory
        if self.choice == "trim":
            memory["trim"] = key == "yes"
            self.choice = None
            self.ctx.message(self.status())
            return
        if self.choice == "method":
            memory["chamfer_method"] = key
            self.choice = None
            self.ctx.message(self.status())
            return
        if key == "trim":
            self.choice = "trim"
        elif key == "poly":
            self.poly = True
        elif key == "multiple":
            self.multiple = True
            self.ctx.message("Mode multiple : plusieurs coins à la suite (Entrée pour terminer).")
        else:
            self.option(key)

    def option(self, key):
        pass

    # -- choix --
    def picked(self, items):
        if not items or self.ask is not None or self.choice is not None:
            return
        item = items[0]
        point = self.ctx.last_pick_doc or item.points()[0]
        self.ctx.scene.clearSelection()
        if self.poly:
            self._apply_poly(item)
            return
        if self.first is None:
            if not self.accepts(item):
                return
            self.first = (item, point)
            self.ctx.highlight([item])
            return
        result = self.compute(self.first[0], self.first[1], item, point)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        changes, created, text = result
        self.ctx.apply_edit(changes if self.ctx.tool_memory["trim"] else [], created, text)
        self.done += 1
        self.first = None
        self.ctx.highlight([])
        if not self.multiple:
            self.finish()

    def selection_done(self, items):
        if items:
            self.picked(items)
            return
        self.finish()

    def accepts(self, item) -> bool:
        return True

    def hover_ghosts(self, item, cursor):
        if self.first is None or item is None or self.ask is not None or self.choice is not None:
            return []
        result = self.compute(self.first[0], self.first[1], item, cursor)
        if isinstance(result, str):
            return []
        changes, created, _text = result
        tol = self.ctx.tess_tol()
        out = []
        if self.ctx.tool_memory["trim"]:
            for changed, geometry in changes:
                out += cad_shapes.display_segments(cad_shapes.prims(changed.kind, {**changed.geometry(), **geometry}),
                                                   tol)
        for kind, geometry, _source in created:
            out += cad_shapes.display_segments(cad_shapes.prims(kind, geometry), tol)
        return out

    def _apply_poly(self, item):
        if item.kind != "cad_pline":
            self.ctx.message("Ce n'est pas une polyligne.", error=True)
            return
        geometry = item.geometry()
        verts, done, skipped = self.poly_edit(geometry["vertices"], bool(geometry.get("closed")))
        if done:
            self.ctx.apply_edit([(item, {"vertices": verts})], [], f"{self.LABEL} (polyligne)")
        self.ctx.message(f"{done} sommet(s) traité(s)" + (f", {skipped} ignoré(s) (trop courts ou courbes)."
                                                          if skipped else "."))
        self.poly = False
        self.finish()

    # -- calcul commun --
    def compute(self, item1, pick1, item2, pick2):
        if item1 is item2:
            if item1.kind != "cad_pline":
                return "Choisissez deux objets différents."
            return self._pline_corner(item1, pick1, pick2)
        return self.compute_pair(item1, pick1, item2, pick2)

    def _pline_corner(self, item, pick1, pick2):
        geometry = item.geometry()
        verts = geometry["vertices"]
        closed = bool(geometry.get("closed")) and len(verts) > 2
        i1, _p1 = cad_shapes.pline_segment_at(geometry, pick1)
        i2, _p2 = cad_shapes.pline_segment_at(geometry, pick2)
        count = len(verts)
        if i1 is None or i2 is None or i1 == i2:
            return "Choisissez deux segments voisins de la polyligne."
        if (i2 - i1) % count == 1:
            vertex = (i1 + 1) % count
        elif (i1 - i2) % count == 1:
            vertex = (i2 + 1) % count
        else:
            return "Les deux segments ne sont pas voisins."
        result = self.vertex_edit(verts, closed, vertex)
        if isinstance(result, str):
            return result
        return [(item, {"vertices": result})], [], self.LABEL


def _line_geometry(item, far, new_end) -> dict:
    """Champs d'une ligne coupee / prolongee : le bout `far` garde sa place (p1 / p2 gardes : sens du type de
    ligne et terminaisons inchanges), l'autre devient `new_end`."""
    a, b = item.points()
    if geo.distance(a, far) <= geo.distance(b, far):
        return {"p1": [far[0], far[1]], "p2": [new_end[0], new_end[1]]}
    return {"p1": [new_end[0], new_end[1]], "p2": [far[0], far[1]]}


class ChamferCommand(_CornerCommand):
    """CHANFREIN (CHA) : deux distances (Distance) ou distance + angle (Angle, Methode), memorisees ; deux lignes
    (ou deux segments voisins d'une polyligne) ajustees et reliees par le chanfrein ; distances nulles = coin vif ;
    Ajuster / Non ajuster ; Polyligne = tous les sommets ; Multiple."""

    NAME = "CHAMFER"
    LABEL = "Chanfrein"
    FIRST_TEXT = "Choisissez la première ligne"
    SECOND_TEXT = "Choisissez la deuxième ligne"

    def status(self) -> str:
        m = self.ctx.tool_memory
        mode = "AJUSTER" if m["trim"] else "NON AJUSTER"
        if m["chamfer_method"] == "angle":
            return f"(Mode {mode}) Longueur = {self.ctx.fmt(m['chamfer_d1'])}, angle = {m['chamfer_angle']:g}°"
        return f"(Mode {mode}) Distance1 = {self.ctx.fmt(m['chamfer_d1'])}, Distance2 = {self.ctx.fmt(m['chamfer_d2'])}"

    def first_options(self):
        return [POLY_OPT, ("distance", "Distance", ("D", "DI", "DISTANCE")), ("angle", "Angle", ("AN", "ANGLE")),
                TRIM_OPT, ("method", "Méthode", ("ME", "METHODE", "MÉTHODE", "METHOD")), MULTI_OPT]

    def option(self, key):
        memory = self.ctx.tool_memory
        if key == "distance":
            memory["chamfer_method"] = "distance"
            self._ask(("chamfer_d1", "Spécifiez la première distance de chanfrein", "length"),
                      ("chamfer_d2", "Spécifiez la deuxième distance de chanfrein", "length"))
        elif key == "angle":
            memory["chamfer_method"] = "angle"
            self._ask(("chamfer_d1", "Spécifiez la longueur du chanfrein sur la première ligne", "length"),
                      ("chamfer_angle", "Spécifiez l'angle du chanfrein depuis la première ligne", "angle"))
        elif key == "method":
            self.choice = "method"

    def accepts(self, item):
        if item.kind not in ("cad_line", "cad_pline"):
            self.ctx.message("Le chanfrein ne s'applique qu'aux lignes et aux polylignes.", error=True)
            return False
        return True

    def _values(self):
        m = self.ctx.tool_memory
        if m["chamfer_method"] == "angle":
            return m["chamfer_d1"], 0.0, m["chamfer_angle"]
        return m["chamfer_d1"], m["chamfer_d2"], None

    def vertex_edit(self, verts, closed, vertex):
        d1, d2, angle = self._values()
        return cad_tools.pline_vertex_edit(verts, closed, vertex, "chamfer", d1, d2, angle)

    def poly_edit(self, verts, closed):
        d1, d2, angle = self._values()
        return cad_tools.pline_all_vertices(verts, closed, "chamfer", d1, d2, angle)

    def compute_pair(self, item1, pick1, item2, pick2):
        if item1.kind != "cad_line" or item2.kind != "cad_line":
            return "Chanfrein entre deux objets : deux lignes (ou deux segments voisins d'une même polyligne)."
        d1, d2, angle = self._values()
        seg1, seg2 = item1.points(), item2.points()
        if angle is not None:
            found = cad_tools.chamfer_angle_distance(seg1, pick1, seg2, pick2, d1, angle)
        else:
            found = cad_tools.chamfer_lines(seg1, pick1, seg2, pick2, d1, d2)
        if isinstance(found, str):
            return found
        changes = [(item1, _line_geometry(item1, *found["first"])), (item2, _line_geometry(item2, *found["second"]))]
        created = []
        if found["chamfer"] is not None:
            c1, c2 = found["chamfer"]
            created.append(("cad_line", {"p1": [c1[0], c1[1]], "p2": [c2[0], c2[1]]}, item1))
        return changes, created, "Chanfrein"


class FilletCommand(_CornerCommand):
    """RACCORD (F) : rayon (memorise), deux objets (lignes, arcs, cercles, ou deux segments voisins d'une
    polyligne) ajustes ou prolonges, arc tangent cree du cote des clics ; rayon 0 = coin vif ; Ajuster / Non
    ajuster ; Polyligne = tous les sommets ; Multiple."""

    NAME = "FILLET"
    LABEL = "Raccord"
    FIRST_TEXT = "Choisissez le premier objet"
    SECOND_TEXT = "Choisissez le deuxième objet"

    def status(self) -> str:
        m = self.ctx.tool_memory
        return f"Paramètres actuels : Mode = {'AJUSTER' if m['trim'] else 'NON AJUSTER'}, " \
               f"Rayon = {self.ctx.fmt(m['fillet_radius'])}"

    def first_options(self):
        return [POLY_OPT, ("radius", "Rayon", ("R", "RAYON", "RADIUS")), TRIM_OPT, MULTI_OPT]

    def option(self, key):
        if key == "radius":
            self._ask(("fillet_radius", "Spécifiez le rayon du raccord", "length"))

    def vertex_edit(self, verts, closed, vertex):
        return cad_tools.pline_vertex_edit(verts, closed, vertex, "fillet", self.ctx.tool_memory["fillet_radius"])

    def poly_edit(self, verts, closed):
        return cad_tools.pline_all_vertices(verts, closed, "fillet", self.ctx.tool_memory["fillet_radius"])

    def compute_pair(self, item1, pick1, item2, pick2):
        if item1.kind == "cad_pline" or item2.kind == "cad_pline":
            return "Raccord d'une polyligne avec un autre objet : pas encore pris en charge (deux segments voisins " \
                   "d'une même polyligne, ou l'option Polyligne)."
        p1, p2 = item1.prims()[0], item2.prims()[0]
        found = cad_tools.fillet_prims(p1, pick1, p2, pick2, self.ctx.tool_memory["fillet_radius"])
        if isinstance(found, str):
            return found
        changes = []
        for item, new in ((item1, found["first"]), (item2, found["second"])):
            if new is None:
                continue                                    # cercle complet : jamais coupe
            if item.kind == "cad_line":
                a, b = new[1], new[2]
                changes.append((item, _line_geometry(item, a, b)))
            elif item.kind == "cad_arc":
                changes.append((item, cad_shapes.arc_data(new[1], new[2], new[3], new[4])))
        created = []
        if found["arc"] is not None:
            created.append(("cad_arc", cad_shapes.arc_data(*found["arc"]), item1))
        return changes, created, "Raccord"


# ==========================================================================
# ROTATION (ROTATE), MIROIR (MIRROR)
# ==========================================================================

def _transform_ghosts(ctx, items, geometry_of) -> list:
    """Segments d'apercu de `items` transformes ; `geometry_of(item)` = champs geometriques transformes."""
    out = []
    for item in items:
        data = item.to_dict()
        data.update(geometry_of(item))
        out.extend(cad_shapes.display_segments(cad_shapes.prims(item.kind, data), ctx.tess_tol()))
    return out


class RotateCommand(_SelectingCommand):
    """ROTATION (RO) : objets, point de base, puis l'angle (point ou valeur en degres) ; options Copier (garde les
    originaux) et Reference (angle de reference puis nouvel angle)."""

    NAME = "ROTATE"
    LABEL = "Rotation"

    def after_selection(self):
        self.base = None
        self.copy = False
        self.stage = "angle"                # angle | ref_old | ref_new
        self.ref = 0.0
        self.ctx.highlight(self.items)

    def step_prompt(self):
        if self.base is None:
            return Prompt("Spécifiez le point de base", [], "point")
        if self.stage == "ref_old":
            return Prompt("Spécifiez l'angle de référence", [], "point", self.base, "0", value="angle")
        if self.stage == "ref_new":
            return Prompt("Spécifiez le nouvel angle", [], "point", self.base, value="angle")
        options = [("copy", "Copier", ("C", "COPIER", "COPY")),
                   ("ref", "Référence", ("R", "REF", "REFERENCE", "RÉFÉRENCE"))]
        return Prompt("Spécifiez l'angle de rotation", options, "point", self.base, "0", value="angle")

    def _angle_of(self, p) -> float:
        return geo.angle_deg(self.base, p)

    def _rotation(self, angle: float) -> float:
        return angle - self.ref if self.stage == "ref_new" else angle

    def point(self, p):
        if self.items is None:
            return
        p = (float(p[0]), float(p[1]))
        if self.base is None:
            self.base = p
            return
        if geo.distance(self.base, p) <= geo.EPS:
            self.ctx.message("Point identique au point de base.", error=True)
            return
        self._angle(self._angle_of(p))

    def value(self, number):
        if self.items is None or self.base is None:
            self.ctx.message("Un point est attendu ici.", error=True)
            return
        self._angle(number)

    def _angle(self, angle: float):
        if self.stage == "ref_old":
            self.ref = angle
            self.stage = "ref_new"
            return
        self._apply(self._rotation(angle))

    def keyword(self, key):
        if key == "copy" and self.base is not None and self.stage == "angle":
            self.copy = True
            self.ctx.message("Rotation avec copie : les objets d'origine sont gardés.")
        elif key == "ref" and self.base is not None and self.stage == "angle":
            self.stage = "ref_old"

    def enter(self):
        self.finish()

    def _geometry(self, item, degrees: float) -> dict:
        return cad_shapes.rotated(item.kind, item.to_dict(), self.base, degrees)

    def _apply(self, degrees: float):
        if self.copy:
            made = self.ctx.create_copies([(item, self._geometry(item, degrees)) for item in self.items])
            self.ctx.commit_created(made, "Rotation (copie)")
        else:
            self.ctx.apply_edit([(item, self._geometry(item, degrees)) for item in self.items], [], "Rotation")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.items is None or self.base is None or self.stage == "ref_old" \
                or geo.distance(self.base, p) <= geo.EPS:
            return []
        degrees = self._rotation(self._angle_of(p))
        return _transform_ghosts(self.ctx, self.items, lambda item: self._geometry(item, degrees))

    def preview(self, p):
        return [("rubber", self.base, p)] if (self.items is not None and self.base is not None) else []


class ScaleCommand(_SelectingCommand):
    """ECHELLE (SC) : objets, point de base, puis le facteur (valeur tapee, ou un point : sa distance au point de base
    dans l'unite du dessin) ; options Copier (garde les originaux) et Reference (longueur de reference puis nouvelle
    longueur : facteur = nouvelle / reference). Mise a l'echelle uniforme (rayons et espacement des hachures compris)."""

    NAME = "SCALE"
    LABEL = "Échelle"

    def after_selection(self):
        self.base = None
        self.copy = False
        self.stage = "factor"               # factor | ref_old | ref_new
        self.ref = 1.0
        self.ctx.highlight(self.items)

    def step_prompt(self):
        if self.base is None:
            return Prompt("Spécifiez le point de base", [], "point")
        if self.stage == "ref_old":
            return Prompt("Spécifiez la longueur de référence", [], "point", self.base, self.ctx.fmt(self.ref),
                          value="length")
        if self.stage == "ref_new":
            return Prompt("Spécifiez la nouvelle longueur", [], "point", self.base, value="length")
        options = [("copy", "Copier", ("C", "COPIER", "COPY")),
                   ("ref", "Référence", ("R", "REF", "REFERENCE", "RÉFÉRENCE"))]
        return Prompt("Spécifiez le facteur d'échelle", options, "point", self.base, "1", value="scale")

    def _factor_of(self, p) -> float:
        distance = geo.distance(self.base, p)
        if self.stage == "ref_new":
            return distance / self.ref
        return distance / (self.ctx.unit() or 1.0)

    def point(self, p):
        if self.items is None:
            return
        p = (float(p[0]), float(p[1]))
        if self.base is None:
            self.base = p
            return
        if geo.distance(self.base, p) <= geo.EPS:
            self.ctx.message("Point identique au point de base.", error=True)
            return
        if self.stage == "ref_old":
            self.ref = geo.distance(self.base, p)
            self.stage = "ref_new"
            return
        self._apply(self._factor_of(p))

    def value(self, number):
        if self.items is None or self.base is None:
            self.ctx.message("Un point est attendu ici.", error=True)
            return
        if number <= geo.EPS:
            self.ctx.message("Le facteur d'échelle doit être supérieur à 0.", error=True)
            return
        if self.stage == "ref_old":
            self.ref = number
            self.stage = "ref_new"
            return
        self._apply(number / self.ref if self.stage == "ref_new" else number)

    def keyword(self, key):
        if key == "copy" and self.base is not None and self.stage == "factor":
            self.copy = True
            self.ctx.message("Échelle avec copie : les objets d'origine sont gardés.")
        elif key == "ref" and self.base is not None and self.stage == "factor":
            self.stage = "ref_old"

    def enter(self):
        self.finish()

    def _geometry(self, item, factor: float) -> dict:
        return cad_shapes.scaled(item.kind, item.to_dict(), self.base, factor)

    def _apply(self, factor: float):
        if factor <= geo.EPS:
            self.ctx.message("Le facteur d'échelle doit être supérieur à 0.", error=True)
            return
        if self.copy:
            made = self.ctx.create_copies([(item, self._geometry(item, factor)) for item in self.items])
            self.ctx.commit_created(made, "Échelle (copie)")
        else:
            self.ctx.apply_edit([(item, self._geometry(item, factor)) for item in self.items], [], "Échelle")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.items is None or self.base is None or self.stage == "ref_old" \
                or geo.distance(self.base, p) <= geo.EPS:
            return []
        factor = self._factor_of(p)
        if factor <= geo.EPS:
            return []
        return _transform_ghosts(self.ctx, self.items, lambda item: self._geometry(item, factor))

    def preview(self, p):
        return [("rubber", self.base, p)] if (self.items is not None and self.base is not None) else []


class MirrorCommand(_SelectingCommand):
    """MIROIR (MI) : objets, deux points de l'axe de symetrie, puis « Effacer les objets source ? » (Non par
    defaut : copies symetriques). Les arcs gardent leur sens, les polylignes leurs renflements (inverses)."""

    NAME = "MIRROR"
    LABEL = "Miroir"

    def after_selection(self):
        self.first = None
        self.second = None
        self.ctx.highlight(self.items)

    def step_prompt(self):
        if self.first is None:
            return Prompt("Spécifiez le premier point de l'axe de symétrie", [], "point")
        if self.second is None:
            return Prompt("Spécifiez le deuxième point de l'axe de symétrie", [], "point", self.first)
        return Prompt("Effacer les objets source ?", [("yes", "Oui", ("O", "OUI", "Y", "YES")),
                                                      ("no", "Non", ("N", "NON", "NO"))], "point", None, "Non")

    def point(self, p):
        if self.items is None:
            return
        p = (float(p[0]), float(p[1]))
        if self.first is None:
            self.first = p
        elif self.second is None:
            if geo.distance(self.first, p) <= geo.EPS:
                self.ctx.message("Les deux points de l'axe sont identiques.", error=True)
                return
            self.second = p
        else:
            self.ctx.message("Répondez Oui ou Non (Entrée = Non).", error=True)

    def keyword(self, key):
        if self.second is not None and key in ("yes", "no"):
            self._apply(key == "yes")

    def enter(self):
        if self.second is not None:
            self._apply(False)
            return
        self.finish()

    def _geometry(self, item, a=None, b=None) -> dict:
        return cad_shapes.mirrored(item.kind, item.to_dict(), a or self.first, b or self.second)

    def _apply(self, delete_source: bool):
        if delete_source:
            self.ctx.apply_edit([(item, self._geometry(item)) for item in self.items], [], "Miroir")
        else:
            made = self.ctx.create_copies([(item, self._geometry(item)) for item in self.items])
            self.ctx.commit_created(made, "Miroir")
        self.finish()

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()

    def ghosts(self, p):
        if self.items is None or self.first is None or self.second is not None \
                or geo.distance(self.first, p) <= geo.EPS:
            return []
        return _transform_ghosts(self.ctx, self.items, lambda item: self._geometry(item, self.first, p))

    def preview(self, p):
        if self.items is None or self.first is None:
            return []
        if self.second is not None:
            return [("rubber", self.first, self.second)]
        return [("rubber", self.first, p)]


# ==========================================================================
# RECTANGLE (RECTANG) : polyligne fermee de quatre sommets (ou huit avec un raccord)
# ==========================================================================

_ROUND = math.tan(math.radians(22.5))            # renflement d'un quart de cercle


def rectangle_vertices(a, b, radius: float = 0.0) -> list:
    """Sommets [[x, y, renflement]] du rectangle de coins opposes a et b (sens trigonometrique), coins arrondis
    de `radius` (limite a la moitie du plus petit cote)."""
    x0, x1 = sorted((a[0], b[0]))
    y0, y1 = sorted((a[1], b[1]))
    r = max(0.0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    if r <= geo.EPS:
        return [[x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0]]
    return [[x0 + r, y0, 0.0], [x1 - r, y0, _ROUND], [x1, y0 + r, 0.0], [x1, y1 - r, _ROUND],
            [x1 - r, y1, 0.0], [x0 + r, y1, _ROUND], [x0, y1 - r, 0.0], [x0, y0 + r, _ROUND]]


class RectangleCommand(Command):
    """RECTANGLE (REC) : premier coin puis coin opposé, ou Dimensions (longueur, largeur, puis le côté) ; Raccord =
    rayon des coins (mémorisé). Une polyligne fermée, comme AutoCAD."""

    NAME = "RECTANGLE"
    LABEL = "Rectangle"

    def start(self):
        self.first = None
        self.stage = "corner"               # corner | length | width | side | radius
        self.length = self.width = 0.0

    def _radius(self) -> float:
        return float(self.ctx.tool_memory.get("rect_radius", 0.0) or 0.0)

    def prompt(self):
        if self.stage == "radius":
            return Prompt("Spécifiez le rayon des coins", [], "point", None, self.ctx.fmt(self._radius()),
                          value="length")
        if self.first is None:
            options = [("radius", "Raccord", ("R", "RAC", "RACCORD", "F", "FILLET"))]
            suffix = f" (rayon = {self.ctx.fmt(self._radius())})" if self._radius() else ""
            return Prompt("Spécifiez le premier coin" + suffix, options, "point")
        if self.stage == "length":
            return Prompt("Spécifiez la longueur du rectangle", [], "point", self.first, value="length")
        if self.stage == "width":
            return Prompt("Spécifiez la largeur du rectangle", [], "point", self.first, value="length")
        if self.stage == "side":
            return Prompt("Spécifiez l'autre coin (côté du rectangle)", [], "point", self.first, "même sens")
        return Prompt("Spécifiez l'autre coin", [("dims", "Dimensions", ("D", "DIM", "DIMENSIONS"))],
                      "point", self.first)

    def keyword(self, key):
        if key == "radius" and self.first is None:
            self.stage = "radius"
        elif key == "dims" and self.first is not None and self.stage == "corner":
            self.stage = "length"

    def value(self, number):
        if self.stage == "radius":
            self.ctx.tool_memory["rect_radius"] = max(0.0, number)
            self.stage = "corner"
        elif self.stage == "length":
            if number <= geo.EPS:
                self.ctx.message("La longueur doit être positive.", error=True)
                return
            self.length = number
            self.stage = "width"
        elif self.stage == "width":
            if number <= geo.EPS:
                self.ctx.message("La largeur doit être positive.", error=True)
                return
            self.width = number
            self.stage = "side"
        else:
            self.ctx.message("Un point est attendu ici.", error=True)

    def _opposite(self, p):
        if self.stage == "side":
            sx = -1.0 if p[0] < self.first[0] else 1.0
            sy = -1.0 if p[1] < self.first[1] else 1.0
            return (self.first[0] + sx * self.length, self.first[1] + sy * self.width)
        return (float(p[0]), float(p[1]))

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.stage == "radius":
            self.ctx.message("Donnez le rayon (valeur).", error=True)
            return
        if self.first is None:
            self.first = p
            return
        if self.stage in ("length", "width"):
            self.value(geo.distance(self.first, p))
            return
        self._make(self._opposite(p))

    def enter(self):
        if self.stage == "radius":
            self.stage = "corner"
            return
        if self.stage == "side":
            self._make((self.first[0] + self.length, self.first[1] + self.width))
            return
        self.finish()

    def _data(self, other) -> dict:
        return {"vertices": rectangle_vertices(self.first, other, self._radius()), "closed": True}

    def _make(self, other):
        if abs(other[0] - self.first[0]) <= geo.EPS or abs(other[1] - self.first[1]) <= geo.EPS:
            self.ctx.message("Rectangle sans épaisseur : refusé.", error=True)
            return
        item = self.ctx.create_entity("cad_pline", self._data(other))
        self.ctx.commit_created([item], "Rectangle")
        self.finish()

    def preview(self, p):
        if self.first is None or self.stage in ("radius", "length", "width"):
            return []
        other = self._opposite(p)
        if abs(other[0] - self.first[0]) <= geo.EPS or abs(other[1] - self.first[1]) <= geo.EPS:
            return []
        return _show(self.ctx, "cad_pline", self._data(other))


# ==========================================================================
# COTATIONS (DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER, DIMANGULAR) — voir cad_dims
# ==========================================================================

def _auto_rotation(p1, p2, pos) -> float:
    """Direction de mesure d'une cotation lineaire d'apres la place de la ligne de cote : horizontale si elle est
    au-dessus / au-dessous des deux points, verticale si elle est a cote."""
    x0, x1 = sorted((p1[0], p2[0]))
    y0, y1 = sorted((p1[1], p2[1]))
    in_x, in_y = x0 <= pos[0] <= x1, y0 <= pos[1] <= y1
    if in_x and not in_y:
        return 0.0
    if in_y and not in_x:
        return 90.0
    return 0.0 if abs(pos[1] - (y0 + y1) / 2.0) >= abs(pos[0] - (x0 + x1) / 2.0) else 90.0


class _DimCommand(Command):
    """Base : la cotation est creee en UNE etape ; `data(pos)` donne ses champs ; apercu = ses traits."""

    IMMEDIATE_PICK = True
    TYPE = "linear"
    TEXT = "Cotation"

    def data(self, pos) -> dict:
        return {}

    def ready(self) -> bool:
        return False

    def _entity(self, pos) -> dict:
        values = {"dim_type": self.TYPE, "pos": [pos[0], pos[1]], "lineweight": 0.0}
        values.update(self.data(pos))
        values.update(self.ctx.dim_style())
        return values

    def _make(self, pos):
        item = self.ctx.create_entity("cad_dim", self._entity(pos))
        self.ctx.commit_created([item], self.TEXT)
        self.finish()

    def ghosts(self, p):
        if not self.ready():
            return []
        found = cad_dims.geometry(self._entity((float(p[0]), float(p[1]))))
        return cad_shapes.display_segments(found["prims"], self.ctx.tess_tol())

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def picked(self, items):
        pass


class DimLinearCommand(_DimCommand):
    """COTATION LINEAIRE (DLI) : deux origines (ou un objet), puis la place de la ligne de cote ; horizontale ou
    verticale d'apres le curseur, ou Horizontale / Verticale / Pivotee."""

    NAME = "DIMLINEAR"
    LABEL = "Cotation linéaire"
    TYPE = "linear"
    TEXT = "Cotation linéaire"
    ALIGNED = False

    def start(self):
        self.p1 = self.p2 = None
        self.picking = False
        self.force = None                   # None (auto) | angle de mesure impose
        self.asking_angle = False

    def ready(self):
        return self.p1 is not None and self.p2 is not None and not self.asking_angle

    def prompt(self):
        if self.asking_angle:
            return Prompt("Spécifiez l'angle de la ligne de cote", [], "point", None, "0", value="angle")
        if self.p1 is None:
            if self.picking:
                return Prompt("Choisissez l'objet à coter", [], "select")
            return Prompt("Spécifiez l'origine de la première ligne d'attache", [], "point", None, "choisir un objet")
        if self.p2 is None:
            return Prompt("Spécifiez l'origine de la deuxième ligne d'attache", [], "point", self.p1)
        options = [] if self.ALIGNED else [("h", "Horizontale", ("H", "HORIZONTALE", "HORIZONTAL")),
                                           ("v", "Verticale", ("V", "VERTICALE", "VERTICAL")),
                                           ("rot", "Pivotée", ("P", "PIVOTEE", "PIVOTÉE", "R", "ROTATED"))]
        return Prompt("Spécifiez l'emplacement de la ligne de cote", options, "point", geo.midpoint(self.p1, self.p2))

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.p1 is None:
            self.p1 = p
        elif self.p2 is None:
            if geo.distance(self.p1, p) <= geo.EPS:
                self.ctx.message("Les deux origines sont identiques.", error=True)
                return
            self.p2 = p
        else:
            self._make(p)

    def picked(self, items):
        if self.p1 is not None or not items:
            return
        item = items[0]
        if item.kind not in ("cad_line", "cad_arc", "cad_pline"):
            self.ctx.message("Choisissez une ligne, un arc ou une polyligne (ou deux points).", error=True)
            return
        a, b = item.points()
        if geo.distance(a, b) <= geo.EPS:
            self.ctx.message("Objet sans longueur à coter.", error=True)
            return
        self.p1, self.p2 = a, b
        self.picking = False

    def keyword(self, key):
        if self.p2 is None or self.ALIGNED:
            return
        if key == "h":
            self.force = 0.0
        elif key == "v":
            self.force = 90.0
        elif key == "rot":
            self.asking_angle = True

    def value(self, number):
        if self.asking_angle:
            self.force = number
            self.asking_angle = False
        else:
            self.ctx.message("Un point est attendu ici.", error=True)

    def enter(self):
        if self.p1 is None and not self.picking:
            self.picking = True
            return
        self.finish()

    def data(self, pos) -> dict:
        out = {"p1": list(self.p1), "p2": list(self.p2)}
        if not self.ALIGNED:
            out["rot"] = self.force if self.force is not None else _auto_rotation(self.p1, self.p2, pos)
        return out

    def preview(self, p):
        if self.p1 is not None and self.p2 is None:
            return [("rubber", self.p1, p)]
        return []


class DimAlignedCommand(DimLinearCommand):
    NAME = "DIMALIGNED"
    LABEL = "Cotation alignée"
    TYPE = "aligned"
    TEXT = "Cotation alignée"
    ALIGNED = True


class _DimCircleCommand(_DimCommand):
    """Rayon / diametre : un cercle ou un arc, puis la place du texte."""

    def start(self):
        self.center = None
        self.point_on = None
        self.radius = 0.0

    def ready(self):
        return self.center is not None

    def prompt(self):
        if self.center is None:
            return Prompt("Choisissez un arc ou un cercle", [], "select")
        return Prompt("Spécifiez l'emplacement de la ligne de cote", [], "point", self.center)

    def picked(self, items):
        if self.center is not None or not items:
            return
        item = items[0]
        if item.kind not in ("cad_arc", "cad_circle"):
            self.ctx.message("Choisissez un arc ou un cercle.", error=True)
            return
        geometry = item.geometry()
        self.center = (float(geometry["center"][0]), float(geometry["center"][1]))
        self.radius = float(geometry["radius"])
        click = self.ctx.last_pick_doc or (self.center[0] + self.radius, self.center[1])
        if geo.distance(click, self.center) > geo.EPS:
            direction = geo.normalize(geo.sub(click, self.center))
        else:
            direction = (1.0, 0.0)
        self.point_on = geo.add(self.center, geo.mul(direction, self.radius))

    def point(self, p):
        if self.center is not None:
            self._make((float(p[0]), float(p[1])))

    def data(self, pos) -> dict:
        return {"p1": list(self.center), "p2": list(self.point_on)}


class DimRadiusCommand(_DimCircleCommand):
    NAME = "DIMRADIUS"
    LABEL = "Cotation de rayon"
    TYPE = "radius"
    TEXT = "Cotation de rayon"


class DimDiameterCommand(_DimCircleCommand):
    NAME = "DIMDIAMETER"
    LABEL = "Cotation de diamètre"
    TYPE = "diameter"
    TEXT = "Cotation de diamètre"


class DimAngularCommand(_DimCommand):
    """COTATION ANGULAIRE (DAN) : deux lignes (angle entre elles), un arc (son ouverture), ou Entree = sommet puis
    deux points ; puis la place de l'arc de cote."""

    NAME = "DIMANGULAR"
    LABEL = "Cotation angulaire"
    TYPE = "angular"
    TEXT = "Cotation angulaire"

    def start(self):
        self.vertex = self.p1 = self.p2 = None
        self.first_line = None              # (ligne, point cliqué)
        self.mode = "pick"                  # pick | vertex

    def ready(self):
        return self.vertex is not None and self.p1 is not None and self.p2 is not None

    def prompt(self):
        if self.mode == "pick" and not self.ready():
            if self.first_line is None:
                return Prompt("Choisissez un arc ou une ligne", [], "select", None, "spécifier le sommet")
            return Prompt("Choisissez la deuxième ligne", [], "select")
        if self.vertex is None:
            return Prompt("Spécifiez le sommet de l'angle", [], "point")
        if self.p1 is None:
            return Prompt("Spécifiez la première extrémité de l'angle", [], "point", self.vertex)
        if self.p2 is None:
            return Prompt("Spécifiez la deuxième extrémité de l'angle", [], "point", self.vertex)
        return Prompt("Spécifiez l'emplacement de l'arc de cote", [], "point", self.vertex)

    def picked(self, items):
        if self.mode != "pick" or not items or self.ready():
            return
        item = items[0]
        click = self.ctx.last_pick_doc or item.points()[0]
        if item.kind == "cad_arc":
            geometry = item.geometry()
            self.vertex = (float(geometry["center"][0]), float(geometry["center"][1]))
            self.p1, self.p2 = item.points()
            return
        if item.kind != "cad_line":
            self.ctx.message("Choisissez une ligne ou un arc.", error=True)
            return
        if self.first_line is None:
            self.first_line = (item, click)
            return
        a, b = self.first_line[0].points()
        c, d = item.points()
        found = geo.line_intersection(a, b, c, d)
        vertex = found[0] if found is not None else None
        if vertex is None:
            self.ctx.message("Les deux lignes sont parallèles : pas d'angle.", error=True)
            self.first_line = None
            return
        self.vertex = (float(vertex[0]), float(vertex[1]))
        self.p1 = (float(self.first_line[1][0]), float(self.first_line[1][1]))
        self.p2 = (float(click[0]), float(click[1]))

    def enter(self):
        if self.mode == "pick" and self.first_line is None and self.vertex is None:
            self.mode = "vertex"
            return
        self.finish()

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.ready():
            self._make(p)
        elif self.mode == "vertex" and self.vertex is None:
            self.vertex = p
        elif self.mode == "vertex" and self.p1 is None:
            self.p1 = p
        elif self.mode == "vertex" and self.p2 is None:
            self.p2 = p

    def data(self, pos) -> dict:
        return {"center": list(self.vertex), "p1": list(self.p1), "p2": list(self.p2)}

    def preview(self, p):
        if self.mode == "vertex" and self.vertex is not None and not self.ready():
            return [("rubber", self.vertex, p)]
        return []


# ==========================================================================
# HACHURES (HATCH) — voir cad_hatch
# ==========================================================================

HATCH_PATTERN_LABELS = {"solid": "Plein", "lines": "Lignes", "cross": "Croisé", "brick": "Briques"}


def _object_loops(items, tol: float) -> list:
    """Contours fermes des objets choisis : cercle et polyligne fermee tels quels, traits ouverts mis bout a bout."""
    loops, loose = [], []
    for item in items:
        if item.kind in ("cad_hatch", "cad_dim", "cad_text"):
            continue
        pieces = cad_shapes.tessellate(item.prims(), tol)
        if item.closed():
            loops.extend([list(p) for p in pts[:-1]] for pts in pieces if len(pts) >= 4)
        else:
            loose.extend((pts[i], pts[i + 1]) for pts in pieces for i in range(len(pts) - 1))
    loops.extend(cad_hatch.chain_loops(loose))
    return loops


class HatchCommand(Command):
    """HACHURES (H) : un POINT INTERNE (la plus petite zone fermee qui l'entoure, ilots fermes en trous) ou Choisir des
    objets (leurs contours fermes) ; Motif (Plein / Lignes / Croise / Briques), Angle, Espacement (valeurs gardees
    d'une fois a l'autre). La hachure est envoyee SOUS les autres objets ; une etape d'annulation par hachure ;
    Entree / Echap = fin."""

    NAME = "HATCH"
    LABEL = "Hachures"
    IMMEDIATE_PICK = True

    def start(self):
        self.mode = "point"                 # point | objects | pattern | angle | spacing
        self.chosen = []
        self.count = 0

    # -- reglages (memoire de la session, sinon Reglages > Module CAD > Hachures) --
    def _pattern(self) -> str:
        found = self.ctx.tool_memory.get("hatch_pattern") or self.ctx.setting("board_cad_hatch_pattern", "lines")
        return found if found in cad_hatch.PATTERNS else "lines"

    def _angle(self) -> float:
        value = self.ctx.tool_memory.get("hatch_angle")
        return float(value if value is not None else self.ctx.setting("board_cad_hatch_angle", 45))

    def _spacing(self) -> float:
        value = self.ctx.tool_memory.get("hatch_spacing")
        if value is not None:
            return float(value)
        return max(1e-3, float(self.ctx.setting("board_cad_hatch_spacing", 300)) / 100.0 * self.ctx.unit())

    def _alpha(self) -> float:
        return float(self.ctx.setting("board_cad_hatch_alpha", 35))

    def status(self) -> str:
        return (f"Motif = {HATCH_PATTERN_LABELS[self._pattern()]}, angle = {self._angle():g}°, "
                f"espacement = {self.ctx.fmt(self._spacing())}")

    def prompt(self):
        if self.mode == "angle":
            return Prompt("Spécifiez l'angle du motif", [], "point", None, f"{self._angle():g}", value="angle")
        if self.mode == "spacing":
            return Prompt("Spécifiez l'espacement du motif", [], "point", None, self.ctx.fmt(self._spacing()),
                          value="length")
        if self.mode == "pattern":
            options = [("p_solid", "Plein", ("PL", "PLEIN", "SOLID", "S")),
                       ("p_lines", "Lignes", ("L", "LIGNES", "LINES", "ANSI31")),
                       ("p_cross", "Croisé", ("C", "CROISE", "CROISÉ", "CROSS", "ANSI37")),
                       ("p_brick", "Briques", ("B", "BRIQUES", "BRICK"))]
            return Prompt("Motif", options, "point", None, HATCH_PATTERN_LABELS[self._pattern()])
        if self.mode == "objects":
            return Prompt("Choisissez les objets de contour", [], "select", None,
                          f"{len(self.chosen)} choisi(s) : Entrée pour hachurer" if self.chosen else "")
        options = [("objects", "Choisir des objets", ("C", "CHOISIR", "O", "OBJETS", "SELECT")),
                   ("pattern", "Motif", ("M", "MOTIF", "P", "PATTERN")),
                   ("angle", "Angle", ("A", "ANGLE")),
                   ("spacing", "Espacement", ("E", "ESP", "ESPACEMENT", "SCALE"))]
        return Prompt(f"Spécifiez un point interne ({self.status()})", options, "point", None, "quitter")

    def keyword(self, key):
        if key.startswith("p_"):
            self.ctx.tool_memory["hatch_pattern"] = key[2:]
            self.mode = "point"
        elif key in ("objects", "pattern", "angle", "spacing") and self.mode == "point":
            self.mode = key
            self.chosen = []

    def value(self, number):
        if self.mode == "angle":
            self.ctx.tool_memory["hatch_angle"] = number
        elif self.mode == "spacing":
            if number <= geo.EPS:
                self.ctx.message("L'espacement doit être positif.", error=True)
                return
            self.ctx.tool_memory["hatch_spacing"] = number
        else:
            self.ctx.message("Un point interne est attendu ici.", error=True)
            return
        self.mode = "point"

    def enter(self):
        if self.mode == "objects" and self.chosen:
            loops = _object_loops(self.chosen, self.ctx.hatch_tol())
            self.chosen = []
            self.mode = "point"
            self.ctx.highlight([])
            if not loops:
                self.ctx.message("Aucun contour fermé dans ces objets.", error=True)
                return
            self._make(loops)
            return
        if self.mode != "point":
            self.mode = "point"
            self.chosen = []
            return
        self.finish()

    def picked(self, items):
        if self.mode != "objects":
            return
        for item in items:
            if item.kind not in ("cad_hatch", "cad_dim", "cad_text") and item not in self.chosen:
                self.chosen.append(item)
        self.ctx.highlight(self.chosen)
        self.ctx.message(f"{len(self.chosen)} objet(s) choisi(s) : Entrée pour hachurer.")

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.enter()                    # Entree a « Choix des objets » : hachurer ce qui est choisi

    def point(self, p):
        if self.mode != "point":
            return
        p = (float(p[0]), float(p[1]))
        found = cad_hatch.find_region(self.ctx.hatch_segments(), p)
        if isinstance(found, str):
            self.ctx.message(found, error=True)
            return
        outer, holes = found
        self._make([outer] + holes)

    def _make(self, loops):
        data = {"loops": [[[float(x), float(y)] for x, y in loop] for loop in loops],
                "hatch_pattern": self._pattern(), "hatch_angle": self._angle(), "hatch_spacing": self._spacing(),
                "hatch_origin": [0.0, 0.0], "hatch_alpha": self._alpha(), "lineweight": 0.0}
        item = self.ctx.create_entity("cad_hatch", data)
        self.ctx.send_to_back(item)
        self.ctx.commit_created([item], "Hachures")
        self.count += 1

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
        super().finish()


# ==========================================================================
# AJUSTER (TRIM) — voir cad_trim
# ==========================================================================

TRIMMABLE = ("cad_line", "cad_arc", "cad_circle", "cad_pline")
TRIM_CUTTING_OPT = ("cutting", "Arêtes de coupe", ("T", "ARETES", "ARÊTES", "CUTTINGEDGES"))
TRIM_FENCE_OPT = ("fence", "Trajet", ("F", "TRAJET", "FENCE"))
TRIM_CROSSING_OPT = ("crossing", "Capture", ("C", "CAPTURE", "CROSSING"))
TRIM_MODE_OPT = ("mode", "mOde", ("O", "MODE"))
TRIM_EDGE_OPT = ("edge", "aRête", ("R", "ARETE", "ARÊTE", "EDGE"))
TRIM_ERASE_OPT = ("erase", "Effacer", ("E", "EFFACER", "ERASE"))
TRIM_MODES = (("quick", "Rapide", ("R", "RAPIDE", "Q", "QUICK")), ("standard", "Standard", ("S", "STANDARD")))
TRIM_EDGES = (("extend", "Prolonger", ("P", "PROLONGER", "E", "EXTEND")),
              ("none", "Sans prolongement", ("S", "SANS", "N", "NO", "NOEXTEND")))


class TrimCommand(Command):
    """AJUSTER (TR), comme AutoCAD 2021+ (TRIM). Mode RAPIDE (par defaut, `board_cad_trim_mode`) : TOUS les objets
    sont des aretes de coupe ; on clique la partie a retirer, on TRACE A MAIN LEVEE (appui + glisser : tout ce que le
    trace croise est ajuste), ou deux clics dans le vide = un trajet de deux points ; un objet que rien ne coupe est
    EFFACE. Mode STANDARD : d'abord les aretes de coupe (Entree = tous les objets), puis les objets ; un clic dans le
    vide = une capture (rectangle). Les deux : Maj + clic = PROLONGER jusqu'a la premiere limite ; options Arêtes de
    coupe, Trajet (plusieurs points, Entree), Capture, mOde, aRête (prolonger les aretes de coupe, EDGEMODE), Effacer,
    annUler. Une etape d'annulation par geste. Lignes, arcs, cercles, polylignes."""

    NAME = "TRIM"
    LABEL = "Ajuster"
    IMMEDIATE_PICK = True

    def start(self):
        memory = self.ctx.tool_memory
        self.mode = memory.get("trim_mode") or self.ctx.setting("board_cad_trim_mode", "quick")
        if self.mode not in ("quick", "standard"):
            self.mode = "quick"
        self.extend_edges = memory.get("trim_edge", bool(self.ctx.setting("board_cad_trim_edge", False)))
        self.cutters = "all" if self.mode == "quick" else None   # None : en train de les choisir
        self.chosen = []
        self.count = 0
        self.step = None                    # None | "fence" | "two" | "crossing" | "mode" | "edge" | "erase"
        self.points = []                    # trajet / capture en cours
        self._path_cache = None
        selection = [i for i in self.ctx.selection()]
        if selection:
            self.cutters = [i for i in selection if self._can_cut(i)]
            self.ctx.scene.clearSelection()
            self.ctx.message(f"{len(self.cutters)} arête(s) de coupe : la sélection.")

    # ------------------------------------------------------------------ invites
    def prompt(self):
        if self.cutters is None:
            default = f"{len(self.chosen)} choisi(s) : Entrée pour continuer" if self.chosen else "tous les objets"
            return Prompt("Choisissez les arêtes de coupe", [], "select", None, default)
        if self.step == "fence":
            if not self.points:
                return Prompt("Spécifiez le premier point du trajet", [], "point")
            return Prompt("Spécifiez le point suivant du trajet", [UNDO_OPT] if len(self.points) > 1 else [],
                          "point", self.points[-1], "ajuster" if len(self.points) > 1 else "")
        if self.step == "two":
            return Prompt("Spécifiez le point suivant du trajet", [], "point", self.points[0])
        if self.step == "crossing":
            if not self.points:
                return Prompt("Spécifiez le premier coin de la capture", [], "point")
            return Prompt("Spécifiez le coin opposé", [], "point")
        if self.step == "mode":
            current = dict((k, label) for k, label, _w in TRIM_MODES)[self.mode]
            return Prompt("Mode d'ajustement", list(TRIM_MODES), "select", None, current)
        if self.step == "edge":
            current = "Prolonger" if self.extend_edges else "Sans prolongement"
            return Prompt("Arêtes de coupe prolongées", list(TRIM_EDGES), "select", None, current)
        if self.step == "erase":
            return Prompt("Choisissez les objets à effacer", [], "select", None, "revenir à l'ajustement")
        options = [TRIM_CUTTING_OPT, TRIM_FENCE_OPT, TRIM_CROSSING_OPT, TRIM_MODE_OPT, TRIM_EDGE_OPT, TRIM_ERASE_OPT]
        if self.count:
            options.append(UNDO_OPT)
        options.append(EXIT_OPT)
        return Prompt("Choisissez l'objet à ajuster ou Maj + clic pour le prolonger", options, "select", None,
                      "quitter")

    def keyword(self, key):
        if self.step == "mode" and key in ("quick", "standard"):
            self.mode = self.ctx.tool_memory["trim_mode"] = key
            if key == "quick" and self.cutters is None:
                self.cutters = "all"
            elif key == "standard" and self.cutters == "all":
                self.cutters, self.chosen = None, []             # Standard : d'abord les aretes de coupe
            self.step = None
            self.ctx.message(f"Mode d'ajustement : {'Rapide' if key == 'quick' else 'Standard'}.")
            return
        if self.step == "edge" and key in ("extend", "none"):
            self.extend_edges = self.ctx.tool_memory["trim_edge"] = key == "extend"
            self.step = None
            return
        if self.step == "fence" and key == "undo":
            if self.points:
                self.points.pop()
            return
        if key == "exit":
            self.finish()
        elif key == "undo" and self.count:
            self.ctx.pane.undo()
            self.count -= 1
        elif key == "cutting":
            self.cutters, self.chosen = None, []
        elif key in ("fence", "crossing", "mode", "edge", "erase"):
            self.step, self.points = key, []

    def enter(self):
        if self.cutters is None:
            self.cutters = list(self.chosen) or "all"
            self.chosen = []
            self.ctx.highlight([])
            return
        if self.step == "fence":
            points, self.step, self.points = self.points, None, []
            if len(points) > 1:
                self._apply(self._path_targets(points))
            return
        if self.step is not None:
            self.step, self.points = None, []
            return
        self.finish()

    def cancel(self):
        if self.step is not None:
            self.step, self.points = None, []
            return
        self.finish()

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.enter()

    # ------------------------------------------------------------------ aretes de coupe
    @staticmethod
    def _can_cut(item) -> bool:
        return not getattr(item, "AREA", False) and item.kind not in ("cad_dim", "cad_text")

    def _cutter_items(self, target, rect=None) -> list:
        """Aretes de coupe pour `target` ; `rect` (document) : seulement celles qui le touchent (aretes non
        prolongees : rien d'autre ne peut le couper — la recherche reste locale, fluide sur un gros dessin)."""
        if self.cutters == "all" or self.cutters is None:
            items = self.ctx._source(rect) if rect is not None and not self.extend_edges else \
                [i for i in self.ctx.cad_items() if i.isVisible()]
        else:
            items = self.cutters
        return [i for i in items if i is not target and self._can_cut(i) and i.scene() is self.ctx.scene]

    def _cutter_prims(self, target, local: bool = True):
        rect = None
        if local:
            x0, y0, x1, y1 = target.doc_bounds() if target.CURVED else _line_box(target)
            rect = (x0 - 1e-6, y0 - 1e-6, x1 + 1e-6, y1 + 1e-6)
        out = []
        for item in self._cutter_items(target, rect):
            out.extend(item.prims())
        return out

    # ------------------------------------------------------------------ choix d'objets
    def picked(self, items):
        if not items:
            return
        if self.cutters is None:
            for item in items:
                if item not in self.chosen and self._can_cut(item):
                    self.chosen.append(item)
            self.ctx.highlight(self.chosen)
            self.ctx.message(f"{len(self.chosen)} arête(s) de coupe : Entrée pour continuer.")
            return
        if self.step == "erase":
            gone = [i for i in items if not i.locked()]
            if gone:
                self.ctx.apply_edit([], [], "Effacer", gone)
                self.count += 1
            return
        if self.step is not None:
            return
        item = items[0]
        point = self.ctx.last_pick_doc
        if point is None:
            return
        if item.locked():
            self.ctx.message("Objet verrouillé.", error=True)
            return
        if getattr(self.ctx, "last_pick_shift", False):
            self._extend(item, point)
            return
        if item.kind not in TRIMMABLE:
            self.ctx.message("On ne peut ajuster que des lignes, arcs, cercles et polylignes.", error=True)
            return
        result = cad_trim.trim_points(item.kind, item.to_dict(), self._cutter_prims(item), [point],
                                      self.mode == "quick", self.extend_edges)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        self._apply({item: [point]}, {item: result})

    def _extend(self, item, point):
        result = cad_trim.extend(item.kind, item.to_dict(), self._cutter_prims(item, local=False), point,
                                 self.extend_edges)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        kind, geometry = result
        if kind == item.kind:
            self.ctx.apply_edit([(item, geometry)], [], "Prolonger")
        else:
            self.ctx.apply_edit([], [(kind, geometry, item)], "Prolonger", [item])
        self.count += 1

    def _apply(self, targets: dict, results: dict | None = None):
        """Ajuste chaque objet en ses points (UNE etape d'annulation pour tout le geste) ; les aretes de coupe sont
        celles d'AVANT le geste."""
        results = dict(results or {})
        for item, points in targets.items():
            if item not in results:
                results[item] = cad_trim.trim_points(item.kind, item.to_dict(), self._cutter_prims(item), points,
                                                     self.mode == "quick", self.extend_edges)
        changes, created, deleted = [], [], []
        for item, result in results.items():
            if isinstance(result, str):
                continue
            if result.get("delete"):
                deleted.append(item)
                continue
            entities = [cad_shapes.prims_to_entity(piece, False) for piece in result["pieces"]]
            kept = False
            for index, (kind, geometry) in enumerate(entities):
                if index == 0 and kind == item.kind:
                    changes.append((item, geometry))           # le premier morceau reste l'objet d'origine
                    kept = True
                else:
                    created.append((kind, geometry, item))
            if not kept:
                deleted.append(item)
        if not (changes or created or deleted):
            if len(targets) != 1:
                self.ctx.message("Le trajet ne croise aucun objet à ajuster.", error=True)
            else:
                result = next(iter(results.values()))
                self.ctx.message(result if isinstance(result, str) else "Rien à ajuster.", error=True)
            return
        self.ctx.apply_edit(changes, created, "Ajuster", deleted)
        self.count += 1

    # ------------------------------------------------------------------ trajets (clôture, main levée, capture)
    def _candidates(self, a, b) -> list:
        rect = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        return [i for i in self.ctx._source(rect) if i.kind in TRIMMABLE and not i.locked()]

    def _path_targets(self, path) -> dict:
        """{objet: [points ou le trajet le croise]}."""
        targets = {}
        for a, b in zip(path, path[1:]):
            for item in self._candidates(a, b):
                hits = cad_trim.path_hits(item.prims(), [a, b])
                if hits:
                    targets.setdefault(item, []).extend(hits)
        return targets

    def _rect_targets(self, a, b) -> dict:
        targets = {}
        for item in self._candidates(a, b):
            hits = cad_trim.rect_hits(item.prims(), a, b)
            if hits:
                targets[item] = hits
        return targets

    def empty_click(self, doc) -> bool:
        """Clic dans le vide a l'invite des objets a ajuster : Rapide = trajet de deux points, Standard = capture."""
        if self.cutters is None or self.step is not None:
            return False
        self.step = "two" if self.mode == "quick" else "crossing"
        self.points = [(float(doc[0]), float(doc[1]))]
        return True

    def wants_path(self) -> bool:
        """Appui + glisser a l'invite des objets a ajuster : trace a main levee."""
        return self.cutters is not None and self.step is None

    def path_done(self, points):
        self._path_cache = None
        if len(points) > 1:
            self._apply(self._path_targets(points))

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.step == "fence":
            if not self.points or geo.distance(self.points[-1], p) > geo.EPS:
                self.points.append(p)
        elif self.step == "two":
            points, self.step, self.points = self.points + [p], None, []
            self._apply(self._path_targets(points))
        elif self.step == "crossing":
            if not self.points:
                self.points = [p]
                return
            a, self.step, self.points = self.points[0], None, []
            self._apply(self._rect_targets(a, p))

    # ------------------------------------------------------------------ aperçus
    def preview(self, p):
        if self.step in ("fence", "two") and self.points:
            path = self.points + [p]
            return [("fence", a, b) for a, b in zip(path, path[1:])]
        if self.step == "crossing" and self.points:
            (x0, y0), (x1, y1) = self.points[0], p
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            return [("fence", a, b) for a, b in zip(corners, corners[1:])]
        return []

    def _removed_ghosts(self, targets: dict) -> list:
        out = []
        tol = self.ctx.tess_tol()
        for item, points in targets.items():
            result = cad_trim.trim_points(item.kind, item.to_dict(), self._cutter_prims(item), points,
                                          self.mode == "quick", self.extend_edges)
            if isinstance(result, str):
                continue
            removed = result["prims"] if result.get("delete") else result["removed"]
            out += cad_shapes.display_segments(removed, tol)
        return out

    def ghosts(self, p):
        """Apercu du trajet / de la capture en cours : les morceaux qui seraient retires."""
        if self.step in ("fence", "two") and self.points:
            return self._removed_ghosts(self._path_targets(self.points + [p]))
        if self.step == "crossing" and self.points:
            return self._removed_ghosts(self._rect_targets(self.points[0], p))
        return []

    def path_ghosts(self, points) -> list:
        """Apercu PENDANT un trace a main levee : seuls les nouveaux segments du trace sont examines (cache des
        points deja poses ; le dernier segment, jusqu'au curseur, est refait a chaque mouvement)."""
        fixed, cursor = points[:-1], points[-1]
        cache = self._path_cache
        if cache is None or cache["count"] > len(fixed):
            cache = self._path_cache = {"count": 1, "targets": {}, "ghosts": {}}
        changed = set()
        for i in range(max(1, cache["count"]), len(fixed)):
            a, b = fixed[i - 1], fixed[i]
            for item in self._candidates(a, b):
                hits = cad_trim.path_hits(item.prims(), [a, b])
                if hits:
                    cache["targets"].setdefault(item, []).extend(hits)
                    changed.add(item)
        cache["count"] = len(fixed)
        for item in changed:
            cache["ghosts"][item] = self._removed_ghosts({item: cache["targets"][item]})
        ghosts = dict(cache["ghosts"])
        if fixed:
            a = fixed[-1]
            for item in self._candidates(a, cursor):
                hits = cad_trim.path_hits(item.prims(), [a, cursor])
                if hits:
                    ghosts[item] = self._removed_ghosts({item: cache["targets"].get(item, []) + hits})
        return [seg for segs in ghosts.values() for seg in segs]

    def hover_ghosts(self, item, cursor):
        """Apercu au survol : le morceau qui serait retire (ou effacé, mode Rapide), le prolongement avec Maj."""
        if self.cutters is None or self.step is not None or item is None or cursor is None:
            return []
        tol = self.ctx.tess_tol()
        if getattr(self.ctx, "shift_held", lambda: False)():
            result = cad_trim.extend(item.kind, item.to_dict(), self._cutter_prims(item, local=False), cursor,
                                     self.extend_edges)
            if isinstance(result, str):
                return []
            return cad_shapes.display_segments(cad_shapes.prims(*result), tol)
        if item.kind not in TRIMMABLE:
            return []
        return self._removed_ghosts({item: [cursor]})

    def finish(self):
        if not self.finished:
            self.ctx.highlight([])
            if self.count:
                self.ctx.message(f"Ajuster : {self.count} modification(s).")
        super().finish()


def _line_box(item) -> tuple:
    a, b = item.points()
    return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])


# ==========================================================================
# TEXTES (TEXT / DTEXT, MTEXT, TEXTEDIT) — voir cad_text
# ==========================================================================
# Saisie du texte : invite de genre « text » — la frappe (espaces compris) va au texte, qui s'affiche AU FUR ET A
# MESURE dans le dessin (`typed`) ; l'entite existe dans la scene des le debut de la saisie mais n'entre dans
# l'annulation qu'a la fin (une etape par commande, comme les lignes).

JUSTIFY_OPT = ("justify", "Justifier", ("J", "JUSTIFIER", "JUSTIFY"))
HEIGHT_OPT = ("height", "Hauteur", ("H", "HAUTEUR", "HEIGHT"))
ROTATION_OPT = ("rotation", "Rotation", ("R", "ROTATION"))
JUSTIFY_OPTIONS = [(code, code, (code,)) for code in cad_text.JUSTIFY]


def _caret(found: dict) -> list:
    """Curseur de saisie (document) : trait vertical apres le dernier caractere de la derniere ligne."""
    s = found["style"]
    h = found["height"]
    if found["lines"]:
        line, x, y = found["lines"][-1]
        x += cad_text._measure(line, s) * h
    else:
        x, y = 0.0, 0.0
    a = cad_text.to_doc(found["origin"], found["rot"], (x + h * 0.08, y - h * 0.2))
    b = cad_text.to_doc(found["origin"], found["rot"], (x + h * 0.08, y + h * 1.15))
    return [(a, b)]


class _TextTyping(Command):
    """Base : etape de saisie du texte (`typing`), entite en cours `self.item`, entites faites `self.made`."""

    MULTILINE = False                       # Entree = nouveau paragraphe (MTEXTE) ; sinon Entree = ligne validee
    TEXT = "Texte"

    def start(self):
        self.item = None
        self.made = []

    def typing(self) -> bool:
        return self.item is not None

    def typing_prompt(self) -> Prompt:
        if self.MULTILINE:
            return Prompt("Texte (Entrée = paragraphe, Ctrl+Entrée / clic droit / clic ailleurs = terminer)", [],
                          "text")
        return Prompt("Texte (Entrée = ligne suivante, Entrée sur une ligne vide = terminer)", [], "text")

    def typed(self, text: str):
        """Saisie en cours : le texte s'affiche dans le dessin a chaque touche."""
        if self.item is not None:
            self.ctx.set_entity_values(self.item, {"text": text})

    def ghosts(self, p):
        if self.item is None or self.item.scene() is None:
            return []
        found = self.item.doc_layout()
        return cad_text.box_segments(found["corners"]) + _caret(found)

    def _close(self):
        """Fin : l'entite en cours est gardee si elle a du texte ; tout ce qui est fait = UNE etape d'annulation."""
        item, self.item = self.item, None
        if item is not None:
            if item.text().strip():
                self.made.append(item)
            else:
                self.ctx.remove_uncommitted(item)
        if self.made:
            self.ctx.commit_created(self.made, self.TEXT)
        self.made = []
        self.finish()

    def cancel(self):
        self._close()


class TextCommand(_TextTyping):
    """TEXTE (TEXT / DT) : point de depart (ou Justifier), hauteur, angle, puis le texte, LIGNE PAR LIGNE : Entree
    valide la ligne et en commence une autre dessous, Entree sur une ligne vide termine ; un clic pose la ligne
    suivante ailleurs. Chaque ligne est une entite (comme AutoCAD)."""

    NAME = "TEXT"
    LABEL = "Texte"
    TEXT = "Texte"

    def start(self):
        super().start()
        style = self.ctx.text_style()
        memory = self.ctx.tool_memory
        self.justify = memory.get("text_justify") or style["justify"]
        self.height = None
        self.rot = None
        self.pos = None
        self.asking_justify = False
        self._height_default = memory.get("text_height") or style["height"]
        self._rot_default = memory.get("text_rot", 0.0)

    def prompt(self):
        if self.asking_justify:
            return Prompt("Justification", JUSTIFY_OPTIONS, "point", None, self.justify)
        if self.pos is None:
            return Prompt(f"Spécifiez le point de départ du texte (justification {self.justify})", [JUSTIFY_OPT],
                          "point")
        if self.height is None:
            return Prompt("Spécifiez la hauteur", [], "point", self.pos, self.ctx.fmt(self._height_default),
                          value="length")
        if self.rot is None:
            return Prompt("Spécifiez l'angle de rotation du texte", [], "point", self.pos,
                          cad_input.format_angle(self._rot_default, 2), value="angle")
        return self.typing_prompt()

    def keyword(self, key):
        if self.asking_justify:
            if key in cad_text.JUSTIFY:
                self.justify = key
                self.ctx.tool_memory["text_justify"] = key
            self.asking_justify = False
        elif key == "justify" and self.pos is None:
            self.asking_justify = True

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.asking_justify:
            return
        if self.pos is None:
            self.pos = p
        elif self.height is None:
            d = geo.distance(self.pos, p)
            if d <= geo.EPS:
                self.ctx.message("Hauteur nulle : refusée.", error=True)
                return
            self._set_height(d)
        elif self.rot is None:
            self._set_rot(geo.angle_deg(self.pos, p) if geo.distance(self.pos, p) > geo.EPS else 0.0)

    def value(self, number):
        if self.height is None and self.pos is not None:
            if number <= 0:
                self.ctx.message("La hauteur doit être > 0.", error=True)
                return
            self._set_height(number)
        elif self.rot is None and self.pos is not None:
            self._set_rot(number)

    def enter(self):
        if self.asking_justify:
            self.asking_justify = False
        elif self.pos is None:
            self.finish()
        elif self.height is None:
            self._set_height(self._height_default)
        elif self.rot is None:
            self._set_rot(self._rot_default)
        else:
            self._close()

    def _set_height(self, h):
        self.height = h
        self.ctx.tool_memory["text_height"] = h

    def _set_rot(self, angle):
        self.rot = angle % 360.0
        self.ctx.tool_memory["text_rot"] = self.rot
        self._new_line(self.pos)

    def _new_line(self, pos):
        style = self.ctx.text_style()
        self.item = self.ctx.create_entity("cad_text", {
            "pos": [pos[0], pos[1]], "text": "", "height": self.height, "rot": self.rot, "justify": self.justify,
            "font": style["font"], "spacing": style["spacing"], "mtext": False})

    def text(self, raw: str):
        """Entree pendant la saisie : ligne validee (ligne vide = fin)."""
        if self.item is None:
            return
        if not raw.strip():
            self._close()
            return
        self.ctx.set_entity_values(self.item, {"text": raw})
        self.made.append(self.item)
        self.item = None
        last = self.made[-1]
        self._new_line(cad_text.next_line(last.to_dict()))

    def click(self, p, raw: str):
        """Clic pendant la saisie : la ligne en cours est gardee, la suivante commence au point cliqué."""
        if self.item is None:
            return
        if raw.strip():
            self.ctx.set_entity_values(self.item, {"text": raw})
            self.made.append(self.item)
            self.item = None
            self._new_line(p)
        else:
            self.ctx.set_entity_values(self.item, {"pos": [p[0], p[1]]})


class MTextCommand(_TextTyping):
    """TEXTE MULTILIGNE (MTEXT / MT / T) : deux coins du cadre (sa largeur coupe les lignes trop longues ; options
    Hauteur, Justifier, Rotation au 2e coin), puis le texte : Entree = nouveau paragraphe, Ctrl+Entree, clic droit
    ou clic ailleurs = termine. UNE entite."""

    NAME = "MTEXT"
    LABEL = "Texte multiligne"
    MULTILINE = True
    TEXT = "Texte multiligne"

    def start(self):
        super().start()
        style = self.ctx.text_style()
        memory = self.ctx.tool_memory
        self.justify = memory.get("mtext_justify") or style["mjustify"]
        self.height = memory.get("text_height") or style["height"]
        self.rot = memory.get("mtext_rot", 0.0)
        self.first = None
        self.asking = None                  # "justify" | "height" | "rotation"

    def prompt(self):
        if self.asking == "justify":
            return Prompt("Justification", JUSTIFY_OPTIONS, "point", None, self.justify)
        if self.asking == "height":
            return Prompt("Spécifiez la hauteur", [], "point", self.first, self.ctx.fmt(self.height), value="length")
        if self.asking == "rotation":
            return Prompt("Spécifiez l'angle de rotation", [], "point", self.first,
                          cad_input.format_angle(self.rot, 2), value="angle")
        if self.item is not None:
            return self.typing_prompt()
        if self.first is None:
            return Prompt(f"Spécifiez le premier coin (hauteur {self.ctx.fmt(self.height)}, "
                          f"justification {self.justify})", [HEIGHT_OPT, JUSTIFY_OPT, ROTATION_OPT], "point")
        return Prompt("Spécifiez le coin opposé", [HEIGHT_OPT, JUSTIFY_OPT, ROTATION_OPT], "point", self.first)

    def keyword(self, key):
        if self.asking == "justify":
            if key in cad_text.JUSTIFY:
                self.justify = key
                self.ctx.tool_memory["mtext_justify"] = key
            self.asking = None
        elif key in ("justify", "height", "rotation") and self.item is None:
            self.asking = key

    def value(self, number):
        if self.asking == "height":
            if number <= 0:
                self.ctx.message("La hauteur doit être > 0.", error=True)
                return
            self.height = number
            self.ctx.tool_memory["text_height"] = number
        elif self.asking == "rotation":
            self.rot = number % 360.0
            self.ctx.tool_memory["mtext_rot"] = self.rot
        self.asking = None

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.asking in ("height", "rotation"):
            base = self.first
            if base is None or geo.distance(base, p) <= geo.EPS:
                self.ctx.message("Donnez une valeur, ou un point distinct du premier coin.", error=True)
                return
            self.value(geo.distance(base, p) if self.asking == "height" else geo.angle_deg(base, p))
            return
        if self.asking == "justify":
            return
        if self.first is None:
            self.first = p
            return
        self._open_box(self.first, p)

    def enter(self):
        if self.asking is not None:
            self.asking = None
        elif self.item is not None:
            self._close()
        else:
            self.finish()

    def _frame(self, a, b):
        """Cadre (local au premier coin, tourne de `rot`) : x0, y0, x1, y1."""
        q = cad_text.to_local(a, self.rot, b)
        return min(0.0, q[0]), min(0.0, q[1]), max(0.0, q[0]), max(0.0, q[1])

    def ghosts(self, p):
        if self.item is not None:
            return super().ghosts(p)
        if self.first is None or p is None or self.asking is not None:
            return []
        x0, y0, x1, y1 = self._frame(self.first, p)
        corners = [cad_text.to_doc(self.first, self.rot, c) for c in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        return cad_text.box_segments(corners)

    def _open_box(self, a, b):
        x0, y0, x1, y1 = self._frame(a, b)
        width = x1 - x0
        if width <= geo.EPS:
            self.ctx.message("Cadre de largeur nulle : donnez un coin opposé à côté du premier.", error=True)
            return
        vertical, horizontal = (self.justify[0], self.justify[1]) if len(self.justify) == 2 else ("T", self.justify)
        x = {"L": x0, "C": (x0 + x1) / 2.0, "R": x1}[horizontal]
        y = {"T": y1, "M": (y0 + y1) / 2.0, "B": y0}[vertical]
        pos = cad_text.to_doc(a, self.rot, (x, y))
        style = self.ctx.text_style()
        self.item = self.ctx.create_entity("cad_text", {
            "pos": [pos[0], pos[1]], "text": "", "height": self.height, "rot": self.rot, "width": width,
            "justify": vertical + horizontal, "font": style["font"], "spacing": style["spacing"], "mtext": True})

    def text(self, raw: str):
        """Fin de la saisie (Ctrl+Entree, clic droit) : le texte tel qu'il est."""
        if self.item is not None:
            self.ctx.set_entity_values(self.item, {"text": raw.strip("\n")})
        self._close()

    def click(self, p, raw: str):
        self.text(raw)


class TextEditCommand(_TextTyping):
    """MODIFIER UN TEXTE (TEXTEDIT / DDEDIT / ED, ou double-clic sur un texte) : le texte choisi est repris dans la
    saisie, modifie EN PLACE ; Entree (Ctrl+Entree pour un texte multiligne) valide en UNE etape d'annulation, Echap
    rend le texte d'origine."""

    NAME = "TEXTEDIT"
    LABEL = "Modifier un texte"
    IMMEDIATE_PICK = True
    TEXT = "Modifier le texte"

    def start(self):
        super().start()
        self.original = None
        self.before = None
        texts = [i for i in self.ctx.selection() if i.kind == "cad_text"]
        if len(texts) == 1:
            self._edit(texts[0])

    @property
    def MULTILINE(self):
        return bool(self.item is not None and self.item.data.get("mtext"))

    def prompt(self):
        if self.item is None:
            return Prompt("Choisissez un texte à modifier", [], "select")
        return self.typing_prompt()

    def picked(self, items):
        texts = [i for i in items if i.kind == "cad_text"]
        if not texts:
            self.ctx.message("Ce n'est pas un texte.", error=True)
            return
        self._edit(texts[0])

    def selection_done(self, items):
        if self.item is None:
            if items:
                self.picked(items)
            else:
                self.finish()

    def _edit(self, item):
        if item.locked():
            self.ctx.message("Texte verrouillé (ou sur un calque verrouillé) : non modifiable.", error=True)
            return
        self.item = item
        self.original = item.text()
        self.before = self.ctx.snapshot_items([item])
        self.ctx.scene.clearSelection()
        self.ctx.set_buffer(self.original)

    def text(self, raw: str):
        item = self.item
        if item is None:
            return
        value = raw.strip("\n") if item.data.get("mtext") else raw
        if not value.strip():
            self.ctx.message("Texte vide : le texte d'origine est gardé (EFFACER pour le supprimer).", error=True)
            value = self.original
        self.ctx.set_entity_values(item, {"text": value})
        self.ctx.push_change(self.before, [item], self.TEXT)
        self.item = None
        self.finish()

    def click(self, p, raw: str):
        self.text(raw)

    def cancel(self):
        if self.item is not None:
            self.ctx.set_entity_values(self.item, {"text": self.original})
            self.item = None
        self.finish()


# ==========================================================================
# DECOMPOSER (EXPLODE / X) : polyligne -> lignes et arcs ; cotation -> traits et texte
# ==========================================================================

def exploded(item) -> list | None:
    """[(type, champs, source des proprietes ou None)] des entites qui remplacent `item` ; None = ne se decompose pas."""
    if item.kind == "cad_pline":
        out = []
        for p in item.prims():
            if cad_shapes.prim_length(p) <= geo.EPS:
                continue
            kind, geometry = cad_shapes.prims_to_entity([p])
            out.append((kind, geometry, item))
        return out
    if item.kind == "cad_dim":
        found = cad_dims.geometry(item.to_dict())
        props = {k: item.data.get(k) for k in ("layer", "color", "linetype", "ltscale")}
        out = []
        for p in found["prims"]:
            if cad_shapes.prim_length(p) <= geo.EPS:
                continue
            kind, geometry = cad_shapes.prims_to_entity([p])
            out.append((kind, {**geometry, **props, "lineweight": 0.0}, None))
        out.append(("cad_text", {**cad_text.from_dim(found), **props}, None))
        return out
    return None


class ExplodeCommand(_SelectingCommand):
    """DECOMPOSER (EXPLODE / X / DECOMPOS) : chaque polyligne choisie (rectangle compris) devient ses lignes et ses
    arcs, chaque cotation ses traits (lignes, arcs) et son texte, avec les memes calque et proprietes ; UNE etape
    d'annulation. Les autres objets ne se decomposent pas (message)."""

    NAME = "EXPLODE"
    LABEL = "Décomposer"

    def after_selection(self):
        created, gone, skipped = [], [], 0
        for item in self.items:
            parts = exploded(item)
            if parts is None:
                skipped += 1
                continue
            created.extend(parts)
            gone.append(item)
        if gone:
            made = self.ctx.apply_edit([], created, "Décomposer", deleted=gone)
            self.ctx.message(f"Décomposer : {len(gone)} objet(s) en {len(made)} objet(s).")
        if skipped:
            self.ctx.message(f"{skipped} objet(s) ne se décompose(nt) pas (seulement polylignes et cotations).",
                             error=not gone)
        self.finish()


# ==========================================================================
# Registre : noms, alias (anglais / francais), commandes immediates et prevues
# ==========================================================================

@dataclass
class Entry:
    name: str
    label: str
    aliases: tuple
    factory: object = None          # classe de Command, ou fonction(ctx) pour une commande immediate
    planned: str = ""               # phase prevue (commande annoncee comme NON disponible)

    @property
    def available(self) -> bool:
        return self.factory is not None and not self.planned


def _immediate(method: str, *args):
    def run(ctx):
        getattr(ctx, method)(*args)
    return run


REGISTRY: list[Entry] = [
    Entry("LINE", "Ligne", ("L", "LIGNE"), LineCommand),
    Entry("MOVE", "Déplacer", ("M", "DEPLACER", "DÉPLACER", "DE"), MoveCommand),
    Entry("COPY", "Copier", ("CO", "CP", "COPIER"), CopyCommand),
    Entry("ERASE", "Effacer", ("E", "EFFACER", "EF", "DELETE"), EraseCommand),
    Entry("MATCHPROP", "Pipette : copier les propriétés", ("MA", "PIPETTE", "CORRESPROP", "PAINTER"), MatchPropCommand),
    Entry("PLINE", "Polyligne", ("PL", "POLYLIGN", "POLYLIGNE"), PlineCommand),
    Entry("CIRCLE", "Cercle", ("C", "CERCLE"), CircleCommand),
    Entry("ARC", "Arc", ("A",), ArcCommand),
    Entry("OFFSET", "Décaler", ("O", "DECALER", "DÉCALER", "DECALAGE"), OffsetCommand),
    Entry("CHAMFER", "Chanfrein", ("CHA", "CHANFREIN"), ChamferCommand),
    Entry("FILLET", "Raccord (arrondi)", ("F", "RACCORD", "ARRONDI"), FilletCommand),
    Entry("LAYER", "Calques", ("LA", "CALQUE", "CA", "LAYERS"), _immediate("open_layers")),
    Entry("PROPERTIES", "Propriétés", ("PR", "PROPRIETES", "PROPRIÉTÉS", "CH", "PROPS"),
          _immediate("toggle_properties")),
    Entry("OSNAP", "Accrochages aux objets", ("OS", "ACCROBJ", "DSETTINGS", "DS", "SE", "PARAMDES"),
          _immediate("open_snap_settings")),
    Entry("U", "Annuler la dernière opération", ("UNDO", "ANNULER"), _immediate("undo")),
    Entry("REDO", "Rétablir", ("RETABLIR", "RÉTABLIR", "MREDO"), _immediate("redo")),
    Entry("ORTHO", "Mode orthogonal (F8)", ("ORTHOMODE",), _immediate("toggle", "ortho")),
    Entry("POLAR", "Suivi polaire (F10)", ("POLAIRE",), _immediate("toggle", "polar")),
    Entry("GRID", "Grille (F7)", ("GRILLE",), _immediate("toggle", "grid")),
    Entry("LWDISPLAY", "Afficher les épaisseurs de ligne", ("LWT", "EPAIS", "EPAISSEURS", "LWDISPLAY"),
          _immediate("toggle", "lineweight")),
    Entry("SNAP", "Accrochage à la grille (F9)", ("RESOL", "SN"), _immediate("toggle", "grid_snap")),
    Entry("DXFOUT", "Exporter les lignes CAD en DXF", ("EXPORTDXF", "DXF"), _immediate("export_file", ".dxf")),
    Entry("DWGOUT", "Exporter les lignes CAD en DWG (ODA File Converter)", ("EXPORTDWG", "DWG"),
          _immediate("export_file", ".dwg")),
    Entry("REGEN", "Régénérer l'affichage", ("RG", "REGENERER"), _immediate("regen")),
    Entry("REGENALL", "Régénérer l'affichage", ("REGNTOUT",), _immediate("regen")),
    Entry("HELP", "Liste des commandes", ("AIDE", "?"), _immediate("help")),
    Entry("CADQUIT", "Quitter le mode CAD", ("CADOFF", "QUITTERCAD"), _immediate("deactivate")),
    # Phases suivantes : declarees pour un message clair, jamais proposees.
    Entry("RECTANGLE", "Rectangle", ("REC", "RECTANG", "RECTANGLE"), RectangleCommand),
    Entry("ROTATE", "Rotation", ("RO", "ROTATION"), RotateCommand),
    Entry("MIRROR", "Miroir", ("MI", "MIROIR"), MirrorCommand),
    Entry("DIMLINEAR", "Cotation linéaire", ("DLI", "COTLIN", "DIMLIN"), DimLinearCommand),
    Entry("DIMALIGNED", "Cotation alignée", ("DAL", "COTALI", "DIMALI"), DimAlignedCommand),
    Entry("DIMRADIUS", "Cotation de rayon", ("DRA", "COTRAY", "DIMRAY"), DimRadiusCommand),
    Entry("DIMDIAMETER", "Cotation de diamètre", ("DDI", "COTDIA", "DIMDIA"), DimDiameterCommand),
    Entry("DIMANGULAR", "Cotation angulaire", ("DAN", "COTANG", "DIMANG"), DimAngularCommand),
    Entry("ELLIPSE", "Ellipse", ("EL",), planned="phase 2"),
    Entry("POLYGON", "Polygone", ("POL", "POLYGONE"), planned="phase 2"),
    Entry("SCALE", "Échelle", ("SC", "ECHELLE", "ÉCHELLE"), ScaleCommand),
    Entry("TRIM", "Ajuster", ("TR", "AJUSTER"), TrimCommand),
    Entry("EXTEND", "Prolonger", ("EX", "PROLONGER"), planned="phase 3"),
    Entry("STRETCH", "Étirer", ("S", "ETIRER"), planned="phase 3"),
    Entry("BREAK", "Couper", ("BR", "COUPURE"), planned="phase 3"),
    Entry("JOIN", "Joindre", ("J", "JOINDRE"), planned="phase 3"),
    Entry("EXPLODE", "Décomposer", ("X", "DECOMPOS", "DECOMPOSER", "DÉCOMPOSER"), ExplodeCommand),
    Entry("ARRAY", "Réseau", ("AR", "RESEAU"), planned="phase 3"),
    Entry("HATCH", "Hachures", ("H", "HA", "HACHURES", "FHACH", "BHATCH"), HatchCommand),
    Entry("TEXT", "Texte", ("DT", "TEXTE", "DTEXT"), TextCommand),
    Entry("MTEXT", "Texte multiligne", ("T", "MT", "TEXTMULT", "MTEXTE"), MTextCommand),
    Entry("TEXTEDIT", "Modifier un texte", ("ED", "DDEDIT", "MODIFTEXTE"), TextEditCommand),
]

_BY_WORD: dict[str, Entry] = {}
for _entry in REGISTRY:
    for _word in (_entry.name, *_entry.aliases):
        _BY_WORD.setdefault(_word.upper(), _entry)


USER_ALIASES: dict[str, Entry] = {}      # alias du fichier .pgp choisi (`cad_aliases.install`) : passent avant ceux d'origine


def lookup_builtin(text: str) -> Entry | None:
    """Commande nommee par un nom ou alias D'ORIGINE (sans les alias de l'utilisateur)."""
    word = (text or "").strip().upper().lstrip("_-").lstrip("_")
    return _BY_WORD.get(word)


def lookup(text: str) -> Entry | None:
    """Commande nommee par `text` (alias de l'utilisateur, puis nom et alias d'origine ; prefixes `_` international /
    `-` sans boite de dialogue ignores)."""
    word = (text or "").strip().upper().lstrip("_-").lstrip("_")
    return USER_ALIASES.get(word) or _BY_WORD.get(word)


def completions(prefix: str, limit: int = 8) -> list[tuple[str, Entry]]:
    """Commandes DISPONIBLES dont un nom ou alias commence par `prefix` (autocompletion) : (mot, commande)."""
    word = (prefix or "").strip().upper().lstrip("_-")
    if not word:
        return []
    out, seen = [], set()
    for alias, entry in USER_ALIASES.items():
        if entry.available and alias.startswith(word) and entry.name not in seen:
            seen.add(entry.name)
            out.append((alias, entry))
    for entry in REGISTRY:
        if not entry.available:
            continue
        for candidate in (entry.name, *entry.aliases):
            if candidate.upper().startswith(word) and entry.name not in seen:
                seen.add(entry.name)
                out.append((candidate.upper() if candidate.upper() == word else entry.name, entry))
                break
    out.sort(key=lambda pair: (pair[0] != word, len(pair[0]), pair[0]))
    return out[:limit]
