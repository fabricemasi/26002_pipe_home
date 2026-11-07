"""Module CAD du board : commandes COURANTES d'AutoCAD ajoutees le 2026-11-04 (meme protocole que `cad_commands`) —
mesure (ID, DIST, AIRE, LISTE), cotations continues et de ligne de base (COTCONTINUE / DIMCONTINUE, COTLIGNEBASE /
DIMBASELINE), REPERE (LEADER), ALLONGER (LENGTHEN), PEDIT (polyligne : clore, ouvrir, joindre, decurviligner,
inverser), ANNEAU (DONUT), NUAGE DE REVISION (REVCLOUD), ORDRE DE TRACE (DRAWORDER), ZOOM. Geometrie dans `cad_draw`.
Inscrites dans le REGISTRE de `cad_commands` a l'import (`register`)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from . import cad_dims, cad_draw, cad_shapes, cad_text, cad_trim
from . import cad_geometry as geo
from .cad_commands import (TRIMMABLE, Command, Prompt, _SelectingCommand, _show, _TextTyping)

YES_NO = [("yes", "Oui", ("O", "OUI", "Y", "YES")), ("no", "Non", ("N", "NON", "NO"))]


def _kind_label(kind: str, data: dict) -> str:
    return {"cad_line": "LIGNE", "cad_arc": "ARC", "cad_circle": "CERCLE", "cad_pline": "POLYLIGNE",
            "cad_dim": "COTATION", "cad_hatch": "HACHURES", "cad_text": "TEXTE MULTILIGNE" if data.get("mtext")
            else "TEXTE", "cad_point": "POINT", "cad_insert": "REFERENCE DE BLOC", "cad_image": "IMAGE",
            "cad_xline": "LIGNE DE CONSTRUCTION", "cad_ray": "DEMI-DROITE"}.get(kind, kind)


def entity_area(kind: str, data: dict):
    """Aire (positive) d'une entite fermee ; None si elle n'est pas fermee."""
    if kind == "cad_circle":
        r = float(data.get("radius") or 0.0)
        return math.pi * r * r
    if kind == "cad_pline" and data.get("closed"):
        return abs(cad_draw.prims_area(cad_shapes.prims(kind, data)))
    if kind == "cad_hatch":
        from . import cad_hatch
        return abs(sum(cad_hatch.signed_area(loop) * (1 if i == 0 else -1)
                       for i, loop in enumerate(cad_hatch.clean_loops(data.get("loops")))))
    return None


# ==========================================================================
# ID, DIST, AIRE, LISTE
# ==========================================================================

class IdCommand(Command):
    """ID : les coordonnees d'un point (dans l'unite du dessin)."""

    NAME = "ID"
    LABEL = "Coordonnées d'un point"

    def prompt(self):
        return Prompt("Spécifiez un point", [], "point")

    def point(self, p):
        self.ctx.message(f"X = {self.ctx.fmt(p[0])}   Y = {self.ctx.fmt(p[1])}")
        self.finish()


class DistCommand(Command):
    """DIST (DI) : deux points -> distance, angle dans le plan XY, delta X, delta Y."""

    NAME = "DIST"
    LABEL = "Distance"

    def start(self):
        self.first = None

    def prompt(self):
        if self.first is None:
            return Prompt("Spécifiez le premier point", [], "point")
        return Prompt("Spécifiez le deuxième point", [], "point", self.first)

    def point(self, p):
        if self.first is None:
            self.first = (float(p[0]), float(p[1]))
            return
        d = geo.distance(self.first, p)
        angle = geo.angle_deg(self.first, p) % 360.0
        fmt = self.ctx.fmt
        self.ctx.message(f"Distance = {fmt(d)},  Angle dans le plan XY = {angle:.4g}°,  "
                         f"Delta X = {fmt(p[0] - self.first[0])},  Delta Y = {fmt(p[1] - self.first[1])}")
        self.finish()

    def preview(self, p):
        return [("rubber", self.first, p)] if self.first is not None else []


class AreaCommand(Command):
    """AIRE (AREA / AI) : des points (contour ferme par le dernier), Entree = aire et perimetre ; option Objet : aire
    et perimetre d'un cercle, d'une polyligne fermee ou d'une hachure."""

    NAME = "AREA"
    LABEL = "Aire"
    IMMEDIATE_PICK = True

    def start(self):
        self.points = []
        self.picking = False

    def prompt(self):
        if self.picking:
            return Prompt("Choisissez les objets", [], "select")
        if not self.points:
            return Prompt("Spécifiez le premier coin", [("object", "Objet", ("O", "OBJET", "OBJECT"))], "point")
        return Prompt("Spécifiez le point suivant", [], "point", self.points[-1], "total")

    def keyword(self, key):
        if key == "object" and not self.points:
            self.picking = True

    def point(self, p):
        self.points.append((float(p[0]), float(p[1])))

    def enter(self):
        if len(self.points) >= 3:
            area = abs(cad_draw.polygon_area(self.points))
            perimeter = sum(geo.distance(a, b) for a, b in zip(self.points, self.points[1:] + self.points[:1]))
            self._report(area, perimeter)
        self.finish()

    def picked(self, items):
        for item in items:
            data = item.to_dict()
            area = entity_area(item.kind, data)
            if area is None:
                self.ctx.message("Choisissez un cercle, une polyligne fermée ou une hachure.", error=True)
                continue
            perimeter = cad_shapes.total_length(item.prims()) if item.kind != "cad_hatch" else \
                sum(geo.distance(a, b) for a, b in item.outline(0.0))
            self._report(area, perimeter)
            self.finish()
            return

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def _report(self, area, perimeter):
        k = self.ctx.unit()
        self.ctx.message(f"Aire = {area / (k * k):.6g} {self.ctx.unit_symbol()}²,  "
                         f"Périmètre = {self.ctx.fmt(perimeter)}")

    def preview(self, p):
        if not self.points:
            return []
        path = self.points + [p, self.points[0]]
        return [("rubber", a, b) for a, b in zip(path, path[1:])]


class ListCommand(_SelectingCommand):
    """LISTE (LI / LS) : pour chaque objet choisi, son type, son calque et ses mesures (longueur, aire, centre,
    rayon, angle, texte…), dans l'historique de la barre de commande."""

    NAME = "LIST"
    LABEL = "Liste"
    EDITS = False

    def after_selection(self):
        fmt, cad = self.ctx.fmt, self.ctx.cad_page()
        from . import cad_model
        for item in self.items[:200]:
            data = item.to_dict()
            layer = cad_model.effective_layer(cad, data.get("layer"))["name"]
            parts = [f"{_kind_label(item.kind, data)}   calque « {layer} »"]
            if item.kind == "cad_line":
                a, b = item.points()
                parts.append(f"de {self.ctx.fmt_point(a)} à {self.ctx.fmt_point(b)}, longueur {fmt(geo.distance(a, b))},"
                             f" angle {geo.angle_deg(a, b) % 360.0:.4g}°")
            elif item.kind in ("cad_arc", "cad_circle"):
                parts.append(f"centre {self.ctx.fmt_point(data['center'])}, rayon {fmt(data['radius'])}")
                if item.kind == "cad_arc":
                    parts.append(f"de {data['start']:.4g}° à {data['end']:.4g}°, longueur "
                                 f"{fmt(cad_shapes.total_length(item.prims()))}")
            elif item.kind == "cad_pline":
                parts.append(f"{len(data.get('vertices') or [])} sommet(s), {'fermée' if data.get('closed') else 'ouverte'}"
                             f", longueur {fmt(cad_shapes.total_length(item.prims()))}")
            elif item.kind == "cad_text":
                parts.append(f"« {cad_text.style_of(data)['text'][:60]} », hauteur {fmt(data.get('height', 0.0))}")
            elif item.kind == "cad_dim":
                parts.append(f"valeur « {cad_dims.geometry(data)['text']} »"
                             + (", associative" if data.get("assoc") else ""))
            elif item.kind == "cad_point":
                parts.append(f"en {self.ctx.fmt_point(data['pos'])}")
            area = entity_area(item.kind, data)
            if area is not None:
                k = self.ctx.unit()
                parts.append(f"aire {area / (k * k):.6g} {self.ctx.unit_symbol()}²")
            self.ctx.message(" ; ".join(parts))
        if len(self.items) > 200:
            self.ctx.message(f"… et {len(self.items) - 200} autre(s) objet(s).")
        self.finish()


# ==========================================================================
# COTATIONS CONTINUES / DE LIGNE DE BASE
# ==========================================================================

class DimContinueCommand(Command):
    """COTATION CONTINUE (DCO) : a partir de la derniere cotation lineaire / alignee (ou d'une cotation choisie :
    option Choisir), chaque point donne une nouvelle cote qui part de la 2e ligne d'attache de la precedente, sur la
    meme ligne de cote. COTATION DE LIGNE DE BASE (DBA) : toutes partent de la 1re origine de la cote de base, chacune
    decalee de l'ecart des lignes de base (`board_cad_dim_baseline`, 375 centiemes)."""

    NAME = "DIMCONTINUE"
    LABEL = "Cotation continue"
    BASELINE = False
    IMMEDIATE_PICK = True

    def start(self):
        self.base = None
        self.made = []
        self.choosing = False
        last = self.ctx.tool_memory.get("last_dim")
        item = self.ctx.scene.item(last) if last else None
        if item is None or item.scene() is not self.ctx.scene or not self._usable(item):
            found = [i for i in self.ctx.cad_items() if self._usable(i)]   # la plus recente du dessin
            item = found[-1] if found else None
        if item is not None:
            self.base = item.to_dict()
        else:
            self.choosing = True

    @staticmethod
    def _usable(item) -> bool:
        return item.kind == "cad_dim" and item.data.get("dim_type") in ("linear", "aligned")

    def prompt(self):
        if self.choosing:
            return Prompt("Choisissez une cotation linéaire ou alignée", [], "select")
        return Prompt("Spécifiez l'origine de la deuxième ligne d'attache",
                      [("select", "Choisir", ("C", "CHOISIR", "S", "SELECT"))], "point", self.base["p2"],
                      "terminer")

    def keyword(self, key):
        if key == "select":
            self.choosing = True

    def picked(self, items):
        dims = [i for i in items if i.kind == "cad_dim" and i.data.get("dim_type") in ("linear", "aligned")]
        if not dims:
            self.ctx.message("Choisissez une cotation linéaire ou alignée.", error=True)
            return
        self.base = dims[0].to_dict()
        self.choosing = False

    def selection_done(self, items):
        if items:
            self.picked(items)
        elif self.base is None:
            self.finish()
        else:
            self.choosing = False

    def _spacing(self) -> float:
        k = self.ctx.unit() * float(self.ctx.setting("board_cad_dim_scale", 100) or 100) / 100.0
        return float(self.ctx.setting("board_cad_dim_baseline", 375) or 0) / 100.0 * k

    def _data(self, p) -> dict:
        base = self.base
        p1 = base["p1"] if self.BASELINE else base["p2"]
        out = {k: base[k] for k in base if k in cad_dims.STYLE_DEFAULTS or k in ("dim_type", "rot", "lineweight",
                                                                                   "layer", "color", "linetype")}
        out.update(p1=list(p1), p2=[float(p[0]), float(p[1])], pos=list(base["pos"]), dim_str="")
        if self.BASELINE:
            angle = base.get("rot", 0.0) if base.get("dim_type") == "linear" else geo.angle_deg(base["p1"], base["p2"])
            n = (-math.sin(math.radians(angle)), math.cos(math.radians(angle)))
            side = (base["pos"][0] - base["p1"][0]) * n[0] + (base["pos"][1] - base["p1"][1]) * n[1]
            step = self._spacing() * (1.0 if side >= 0 else -1.0)
            out["pos"] = [base["pos"][0] + n[0] * step, base["pos"][1] + n[1] * step]
        link = self.ctx.snap_link(p)
        assoc = {}
        old = base.get("assoc") or {}
        if old.get("p1" if self.BASELINE else "p2"):
            assoc["p1"] = list(old["p1" if self.BASELINE else "p2"])
        if link is not None:
            assoc["p2"] = link
        out["assoc"] = assoc
        return out

    def point(self, p):
        if self.base is None:
            return
        data = self._data(p)
        if geo.distance(data["p1"], data["p2"]) <= geo.EPS:
            self.ctx.message("Origine confondue avec la précédente.", error=True)
            return
        item = self.ctx.create_entity("cad_dim", data)
        self.made.append(item)
        self.base = item.to_dict() if not self.BASELINE else {**self.base, "pos": data["pos"]}

    def enter(self):
        self.finish()

    def finish(self):
        if not self.finished and self.made:
            self.ctx.commit_created(self.made, self.LABEL)
            self.ctx.tool_memory["last_dim"] = self.made[-1].item_id
        super().finish()

    def ghosts(self, p):
        if self.base is None or self.choosing:
            return []
        data = self._data(p)
        if geo.distance(data["p1"], data["p2"]) <= geo.EPS:
            return []
        return cad_shapes.display_segments(cad_dims.geometry(data)["prims"], self.ctx.tess_tol())


class DimBaselineCommand(DimContinueCommand):
    NAME = "DIMBASELINE"
    LABEL = "Cotation de ligne de base"
    BASELINE = True


# ==========================================================================
# REPERE (LEADER)
# ==========================================================================

class LeaderCommand(_TextTyping):
    """REPERE (LE / QLEADER) : la pointe de la fleche, puis les points de la ligne de repere (Entree termine), puis le
    texte (multiligne, comme MTEXTE : Entree = paragraphe, Ctrl+Entree / clic ailleurs = fin) au bout d'un palier
    horizontal. Une polyligne, une fleche pleine (hachure) et un texte ; UNE etape d'annulation."""

    NAME = "LEADER"
    LABEL = "Repère"
    MULTILINE = True
    TEXT = "Repère"

    def start(self):
        super().start()
        self.points = []
        self.parts = []

    def prompt(self):
        if self.item is not None:
            return self.typing_prompt()
        if not self.points:
            return Prompt("Spécifiez le point de la flèche du repère", [], "point")
        return Prompt("Spécifiez le point suivant", [], "point", self.points[-1], "texte" if len(self.points) > 1 else "")

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        if self.item is not None:
            return
        if self.points and geo.distance(self.points[-1], p) <= geo.EPS:
            return
        self.points.append(p)

    def enter(self):
        if self.item is not None:
            self._close()
        elif len(self.points) >= 2:
            self._open_text()
        else:
            self.finish()

    def _arrow(self) -> list:
        style = self.ctx.dim_style()
        size = float(style.get("dim_arrow", 2.5 * self.ctx.unit()))
        tip, nxt = self.points[0], self.points[1]
        d = geo.normalize(geo.sub(nxt, tip))
        n = (-d[1], d[0])
        back = geo.add(tip, geo.mul(d, size))
        half = size / 6.0
        return [list(tip), list(geo.add(back, geo.mul(n, half))), list(geo.sub(back, geo.mul(n, half)))]

    def _open_text(self):
        style = self.ctx.text_style()
        height = float(self.ctx.tool_memory.get("text_height") or style["height"])
        last, before = self.points[-1], self.points[-2]
        right = last[0] >= before[0]
        landing = geo.add(last, (height * (1.0 if right else -1.0), 0.0))
        self.parts.append(self.ctx.create_entity("cad_pline", {"vertices": [[x, y, 0.0] for x, y in self.points + [landing]],
                                                                "closed": False}))
        self.parts.append(self.ctx.create_entity("cad_hatch", {"loops": [self._arrow()], "hatch_pattern": "solid",
                                                                "hatch_alpha": 100.0, "lineweight": 0.0}))
        pos = geo.add(landing, (height * 0.3 * (1.0 if right else -1.0), 0.0))
        self.item = self.ctx.create_entity("cad_text", {
            "pos": [pos[0], pos[1]], "text": "", "height": height, "rot": 0.0, "width": 0.0,
            "justify": "ML" if right else "MR", "font": style["font"], "spacing": style["spacing"], "mtext": True})

    def text(self, raw: str):
        if self.item is not None:
            self.ctx.set_entity_values(self.item, {"text": raw.strip("\n")})
        self._close()

    def click(self, p, raw: str):
        self.text(raw)

    def _close(self):
        self.made.extend(self.parts)                    # la ligne et la fleche restent meme sans texte
        self.parts = []
        super()._close()

    def cancel(self):
        if self.item is None and not self.parts:
            self.finish()
            return
        self._close()

    def preview(self, p):
        if self.item is not None or not self.points:
            return []
        path = self.points + [p]
        return [("rubber", a, b) for a, b in zip(path, path[1:])]


# ==========================================================================
# ALLONGER (LEN)
# ==========================================================================

class LengthenCommand(Command):
    """ALLONGER (LEN) : options DElta (longueur ajoutee, negative = raccourcir), Pourcentage, Total (longueur
    finale), DYnamique (le bout suit le curseur) ; puis chaque clic sur une ligne, un arc ou une polyligne ouverte
    l'allonge du cote du bout le plus proche. Valeurs retenues pour la session ; une etape par objet."""

    NAME = "LENGTHEN"
    LABEL = "Allonger"
    IMMEDIATE_PICK = True
    MODIFY = True
    OPTIONS = [("delta", "DElta", ("DE", "DELTA")), ("percent", "Pourcentage", ("P", "POURCENTAGE", "PERCENT")),
               ("total", "Total", ("T", "TOTAL")), ("dynamic", "DYnamique", ("DY", "DYNAMIQUE", "DYNAMIC"))]

    def start(self):
        memory = self.ctx.tool_memory.get("lengthen") or {}
        self.mode = memory.get("mode", "delta")
        self.amount = memory.get("amount", 0.0)
        self.asking = False
        self.target = None                  # dynamique : (objet, point choisi)

    def prompt(self):
        if self.asking:
            labels = {"delta": "Entrez la longueur à ajouter", "percent": "Entrez le pourcentage de la longueur",
                      "total": "Spécifiez la longueur totale"}
            value = "count" if self.mode == "percent" else "length"
            return Prompt(labels[self.mode], [], "point", None, value=value)
        if self.target is not None:
            return Prompt("Spécifiez le nouveau point d'extrémité", [], "point", self.target[1])
        current = {"delta": f"delta {self.ctx.fmt(self.amount)}", "percent": f"{self.amount:g} %",
                   "total": f"total {self.ctx.fmt(self.amount)}", "dynamic": "dynamique"}[self.mode]
        return Prompt(f"Choisissez l'objet à modifier ({current})", list(self.OPTIONS), "select", None, "quitter")

    def keyword(self, key):
        if key in ("delta", "percent", "total", "dynamic"):
            self.mode = key
            self.asking = key != "dynamic"
            self._remember()

    def value(self, number):
        if self.asking:
            self.amount = number
            self.asking = False
            self._remember()

    def _remember(self):
        self.ctx.tool_memory["lengthen"] = {"mode": self.mode, "amount": self.amount}

    def picked(self, items):
        items = [i for i in items if i.kind in ("cad_line", "cad_arc", "cad_pline") and not i.locked()]
        if not items:
            self.ctx.message("Lignes, arcs et polylignes ouvertes (non verrouillées) seulement.", error=True)
            return
        item, pick = items[0], self.ctx.last_pick_doc
        if self.mode == "dynamic":
            self.target = (item, pick)
            return
        self._apply(item, pick, self.mode, self.amount)

    def _apply(self, item, pick, mode, amount):
        result = cad_draw.lengthened(item.kind, item.to_dict(), pick, mode, amount)
        if isinstance(result, str):
            self.ctx.message(result, error=True)
            return
        self.ctx.apply_edit([(item, result)], [], "Allonger")

    def _dynamic_length(self, p) -> float:
        item, pick = self.target
        primitives = item.prims()
        start, end = cad_shapes.prim_start(primitives[0]), cad_shapes.prim_end(primitives[-1])
        fixed = start if geo.distance(pick, end) <= geo.distance(pick, start) else end
        if item.kind == "cad_arc":
            c, r = primitives[0][1], primitives[0][2]
            a_fixed = geo.angle_deg(c, fixed)
            sweep = (geo.angle_deg(c, p) - a_fixed) % 360.0 if fixed == start else (a_fixed - geo.angle_deg(c, p)) % 360.0
            return math.radians(sweep) * r
        total = cad_shapes.total_length(primitives)
        moving = end if fixed == start else start
        d = geo.normalize(geo.sub(moving, fixed))
        if item.kind == "cad_line":
            return max(geo.EPS, (p[0] - fixed[0]) * d[0] + (p[1] - fixed[1]) * d[1])
        last = primitives[-1] if fixed == start else cad_shapes.reversed_prim(primitives[0])
        seg_start = cad_shapes.prim_start(last)
        dd = geo.normalize(geo.sub(cad_shapes.prim_end(last), seg_start))
        new_seg = (p[0] - seg_start[0]) * dd[0] + (p[1] - seg_start[1]) * dd[1]
        return total - cad_shapes.prim_length(last) + new_seg

    def point(self, p):
        if self.target is None:
            return
        item, pick = self.target
        self.target = None
        self._apply(item, pick, "total", self._dynamic_length(p))

    def enter(self):
        if self.asking:
            self.asking = False
            return
        self.finish()

    def ghosts(self, p):
        if self.target is None:
            return []
        item, pick = self.target
        result = cad_draw.lengthened(item.kind, item.to_dict(), pick, "total", self._dynamic_length(p))
        if isinstance(result, str):
            return []
        data = item.to_dict()
        data.update(result)
        return cad_shapes.display_segments(cad_shapes.prims(item.kind, data), self.ctx.tess_tol())


# ==========================================================================
# PEDIT
# ==========================================================================

class PeditCommand(Command):
    """PEDIT (PE) : une polyligne (une ligne ou un arc : proposee en polyligne, comme AutoCAD) puis Clore / Ouvrir,
    Joindre (les objets choisis mis bout a bout avec elle, voir JOINDRE), Décurviligner (segments droits), Inverser
    (sens), Quitter. Une etape par option."""

    NAME = "PEDIT"
    LABEL = "Modifier une polyligne"
    IMMEDIATE_PICK = True
    MODIFY = True

    def start(self):
        self.item = None
        self.convert = None                 # ligne / arc choisi : (objet) en attente du Oui
        self.joining = False

    def prompt(self):
        if self.convert is not None:
            return Prompt("L'objet choisi n'est pas une polyligne : la convertir", YES_NO, "select", None, "Oui")
        if self.item is None:
            return Prompt("Choisissez une polyligne", [], "select")
        if self.joining:
            return Prompt("Choisissez les objets à joindre", [], "select")
        closed = bool(self.item.data.get("closed"))
        options = [("open", "Ouvrir", ("O", "OUVRIR", "OPEN")) if closed else ("close", "Clore", ("C", "CLORE", "CLOSE")),
                   ("join", "Joindre", ("J", "JOINDRE", "JOIN")),
                   ("decurve", "Décurviligner", ("D", "DECURVILIGNER", "DÉCURVILIGNER", "DECURVE")),
                   ("reverse", "Inverser", ("I", "INVERSER", "R", "REVERSE")),
                   ("exit", "Quitter", ("Q", "QUITTER", "X", "EXIT"))]
        return Prompt("Entrez une option", options, "select", None, "Quitter")

    def picked(self, items):
        if self.joining:
            self._join(items)
            return
        if self.item is not None or self.convert is not None:
            return
        items = [i for i in items if not i.locked()]
        if not items:
            return
        item = items[0]
        if item.kind == "cad_pline":
            self.item = item
        elif item.kind in ("cad_line", "cad_arc"):
            self.convert = item
        else:
            self.ctx.message("Choisissez une polyligne, une ligne ou un arc.", error=True)

    def selection_done(self, items):
        if items:
            self.picked(items)
            if self.joining and items:
                return
        elif self.joining:
            self.joining = False
        elif self.convert is not None:
            self.keyword("yes")
        else:
            self.finish()

    def keyword(self, key):
        if self.convert is not None:
            if key == "yes":
                item = self.convert
                self.convert = None
                made = self.ctx.apply_edit([], [("cad_pline", _as_pline(item), item)], "Convertir en polyligne",
                                           [item])
                self.item = made[0] if made else None
            else:
                self.finish()
            return
        if self.item is None:
            return
        data = self.item.to_dict()
        if key in ("close", "open"):
            self.ctx.apply_edit([(self.item, {"vertices": data["vertices"], "closed": key == "close"})], [],
                                "Clore" if key == "close" else "Ouvrir")
        elif key == "decurve":
            self.ctx.apply_edit([(self.item, {"vertices": [[v[0], v[1], 0.0] for v in data["vertices"]],
                                              "closed": data.get("closed", False)})], [], "Décurviligner")
        elif key == "reverse":
            prims = cad_draw.reverse(cad_shapes.prims("cad_pline", data))
            kind, geometry = cad_shapes.prims_to_entity(prims, bool(data.get("closed")))
            if kind == "cad_pline":
                self.ctx.apply_edit([(self.item, geometry)], [], "Inverser")
        elif key == "join":
            if data.get("closed"):
                self.ctx.message("Polyligne fermée : rien à joindre.", error=True)
                return
            self.joining = True
            self.ctx.begin_object_selection()
        elif key == "exit":
            self.finish()

    def _join(self, items):
        self.joining = False
        others = [i for i in items if i is not self.item and i.kind in ("cad_line", "cad_arc", "cad_pline")
                  and not cad_trim.is_closed(i.kind, i.to_dict()) and not i.locked()]
        if not others:
            return
        pieces = [(self.item.prims(), self.item)] + [(i.prims(), i) for i in others]
        tol = 1e-6
        chains = cad_draw.chain(pieces, tol)
        mine = next(c for c in chains if any(key is self.item for _p, key in c))
        if len(mine) < 2:
            self.ctx.message("Aucun objet ne touche la polyligne par ses extrémités.", error=True)
            return
        kind, geometry = cad_draw.joined(mine, tol)
        if kind != "cad_pline":
            kind, geometry = "cad_pline", _as_pline_prims([p for prims, _k in mine for p in prims])
        gone = [key for _p, key in mine if key is not self.item]
        self.ctx.apply_edit([(self.item, geometry)], [], "Joindre", gone)
        self.ctx.message(f"{len(gone)} objet(s) joint(s) à la polyligne.")


def _as_pline(item) -> dict:
    return _as_pline_prims(item.prims())


def _as_pline_prims(primitives) -> dict:
    vertices = []
    for p in primitives:
        start = cad_shapes.prim_start(p)
        bulge = 0.0 if p[0] == "segment" else cad_shapes.arc_bulge(p[4])
        vertices.append([start[0], start[1], bulge])
    end = cad_shapes.prim_end(primitives[-1])
    vertices.append([end[0], end[1], 0.0])
    return {"vertices": vertices, "closed": False}


# ==========================================================================
# ANNEAU (DONUT), NUAGE DE REVISION (REVCLOUD)
# ==========================================================================

class DonutCommand(Command):
    """ANNEAU (DO / DONUT) : diametre interieur, diametre exterieur (retenus), puis un anneau a chaque clic (Entree
    termine) : un cercle-polyligne dont l'EPAISSEUR fait l'anneau ; interieur 0 = disque plein (hachure pleine)."""

    NAME = "DONUT"
    LABEL = "Anneau"

    def start(self):
        memory = self.ctx.tool_memory.get("donut") or {}
        unit = self.ctx.unit()
        self.inner = memory.get("inner", 0.5 * unit)
        self.outer = memory.get("outer", 1.0 * unit)
        self.stage = "inner"
        self.made = []

    def prompt(self):
        if self.stage == "inner":
            return Prompt("Spécifiez le diamètre intérieur de l'anneau", [], "point", None, self.ctx.fmt(self.inner),
                          value="length")
        if self.stage == "outer":
            return Prompt("Spécifiez le diamètre extérieur de l'anneau", [], "point", None, self.ctx.fmt(self.outer),
                          value="length")
        return Prompt("Spécifiez le centre de l'anneau", [], "point", None, "terminer" if self.made else "")

    def value(self, number):
        if self.stage == "inner":
            self.inner = max(0.0, number)
            self.stage = "outer"
        elif self.stage == "outer":
            if number <= self.inner + geo.EPS:
                self.ctx.message("Le diamètre extérieur doit dépasser l'intérieur.", error=True)
                return
            self.outer = number
            self.stage = "center"
            self.ctx.tool_memory["donut"] = {"inner": self.inner, "outer": self.outer}

    def enter(self):
        if self.stage == "inner":
            self.stage = "outer"
        elif self.stage == "outer":
            self.value(self.outer)
        else:
            self.finish()

    def _data(self, p):
        if self.inner <= geo.EPS:
            r = self.outer / 2.0
            loop = [list(cad_shapes.arc_point(p, r, a)) for a in range(0, 360, 5)]
            return "cad_hatch", {"loops": [loop], "hatch_pattern": "solid", "hatch_alpha": 100.0, "lineweight": 0.0}
        r = (self.inner + self.outer) / 4.0
        width = (self.outer - self.inner) / 2.0
        return "cad_pline", {"vertices": [[p[0] - r, p[1], 1.0], [p[0] + r, p[1], 1.0]], "closed": True,
                             "lineweight": width}

    def point(self, p):
        if self.stage != "center":
            self.ctx.message("Donnez d'abord les diamètres (valeurs).", error=True)
            return
        kind, data = self._data((float(p[0]), float(p[1])))
        self.made.append(self.ctx.create_entity(kind, data))

    def finish(self):
        if not self.finished and self.made:
            self.ctx.commit_created(self.made, "Anneau")
        super().finish()

    def preview(self, p):
        if self.stage != "center":
            return []
        kind, data = self._data((float(p[0]), float(p[1])))
        if kind == "cad_hatch":
            return _show(self.ctx, "cad_circle", {"center": list(p), "radius": self.outer / 2.0})
        return _show(self.ctx, "cad_circle", {"center": list(p), "radius": self.outer / 2.0}) + \
            _show(self.ctx, "cad_circle", {"center": list(p), "radius": self.inner / 2.0})


class RevcloudCommand(Command):
    """NUAGE DE REVISION (REVCLOUD / NUAGEREV) : Rectangulaire (deux coins, par defaut), Polygonal (points, Entree), ou
    Objet (un cercle / une polyligne fermee devient un nuage) ; option Longueur d'arc (retenue). Une polyligne fermee
    d'arcs bombes vers l'exterieur."""

    NAME = "REVCLOUD"
    LABEL = "Nuage de révision"
    IMMEDIATE_PICK = True

    def start(self):
        self.mode = "rect"
        self.points = []
        self.asking = False

    def _arc(self) -> float:
        return float(self.ctx.tool_memory.get("revcloud_arc") or 15.0 * self.ctx.unit())

    def prompt(self):
        if self.asking:
            return Prompt("Spécifiez la longueur d'arc", [], "point", None, self.ctx.fmt(self._arc()), value="length")
        if self.mode == "object":
            return Prompt("Choisissez l'objet", [], "select")
        options = [("arc", "Longueur d'arc", ("L", "LONGUEUR", "A", "ARC")),
                   ("rect", "Rectangulaire", ("R", "RECTANGULAIRE")), ("poly", "Polygonal", ("P", "POLYGONAL")),
                   ("object", "Objet", ("O", "OBJET", "OBJECT"))]
        if not self.points:
            return Prompt("Spécifiez le premier point", options, "point")
        if self.mode == "rect":
            return Prompt("Spécifiez le coin opposé", [], "point", self.points[0])
        return Prompt("Spécifiez le point suivant", [], "point", self.points[-1], "fermer" if len(self.points) > 2 else "")

    def keyword(self, key):
        if key == "arc":
            self.asking = True
        elif key in ("rect", "poly", "object") and not self.points:
            self.mode = key

    def value(self, number):
        if self.asking:
            if number > geo.EPS:
                self.ctx.tool_memory["revcloud_arc"] = number
            self.asking = False

    def point(self, p):
        p = (float(p[0]), float(p[1]))
        self.points.append(p)
        if self.mode == "rect" and len(self.points) == 2:
            (x0, y0), (x1, y1) = self.points
            if abs(x1 - x0) <= geo.EPS or abs(y1 - y0) <= geo.EPS:
                self.ctx.message("Rectangle sans épaisseur.", error=True)
                self.points.pop()
                return
            self._make([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    def enter(self):
        if self.asking:
            self.asking = False
        elif self.mode == "poly" and len(self.points) >= 3:
            self._make(self.points)
        else:
            self.finish()

    def picked(self, items):
        for item in items:
            if item.kind == "cad_circle" or (item.kind == "cad_pline" and item.data.get("closed")):
                outline = [a for a, _b in item.outline(self._arc() / 8.0)]
                if len(outline) >= 3:
                    made = self._vertices(outline)
                    self.ctx.apply_edit([], [("cad_pline", {"vertices": made, "closed": True}, item)],
                                        "Nuage de révision", [item])
                    self.finish()
                    return
        self.ctx.message("Choisissez un cercle ou une polyligne fermée.", error=True)

    def selection_done(self, items):
        if items:
            self.picked(items)
        else:
            self.finish()

    def _vertices(self, outline):
        return cad_draw.revcloud_vertices(outline, self._arc())

    def _make(self, outline):
        vertices = self._vertices(outline)
        if not vertices:
            self.ctx.message("Contour trop petit.", error=True)
            return
        item = self.ctx.create_entity("cad_pline", {"vertices": vertices, "closed": True})
        self.ctx.commit_created([item], "Nuage de révision")
        self.finish()

    def preview(self, p):
        if not self.points:
            return []
        if self.mode == "rect":
            (x0, y0), (x1, y1) = self.points[0], p
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        else:
            corners = self.points + [p, self.points[0]]
        return [("rubber", a, b) for a, b in zip(corners, corners[1:])]


# ==========================================================================
# ORDRE DE TRACE (DRAWORDER), ZOOM
# ==========================================================================

class DrawOrderCommand(_SelectingCommand):
    """ORDRE DE TRACE (DR / ORDRETRACE) : les objets, puis Au-dessus des objets / Au-dessous des objets (un objet de
    reference) / Premier plan / Arrière-plan (par defaut). Une etape d'annulation (ordre du board)."""

    NAME = "DRAWORDER"
    LABEL = "Ordre de tracé"

    def after_selection(self):
        self.stage = "option"
        self.where = None

    def step_prompt(self):
        if self.stage == "ref":
            return Prompt("Choisissez les objets de référence", [], "select")
        return Prompt("Entrez une option d'ordre des objets",
                      [("above", "Au-dessus des objets", ("A", "AU-DESSUS", "ABOVE")),
                       ("under", "Au-dessous des objets", ("U", "AU-DESSOUS", "UNDER")),
                       ("front", "Premier plan", ("P", "PREMIER", "F", "FRONT")),
                       ("back", "Arrière-plan", ("R", "ARRIERE", "ARRIÈRE", "B", "BACK"))], "select", None,
                      "Arrière-plan")

    def keyword(self, key):
        scene = self.ctx.scene
        if key == "front":
            scene.bring_to_front(self.items)
            self.finish()
        elif key == "back":
            scene.send_to_back(self.items)
            self.finish()
        elif key in ("above", "under"):
            self.where = key
            self.stage = "ref"
            self.ctx.begin_object_selection()

    def selection_done(self, items):
        if self.items is None:
            return super().selection_done(items)
        if self.stage == "option":
            self.keyword("back")                        # Entree : la valeur proposee
            return
        refs = [i for i in items if i not in self.items]
        if not refs:
            self.ctx.message("Aucun objet de référence.", error=True)
            self.finish()
            return
        scene = self.ctx.scene
        if self.where == "above":
            top = max(i.zValue() for i in refs)
            scene._restack(self.items, lambda order: [top + 0.001 * (n + 1) for n in range(len(order))],
                           "Au-dessus des objets")
        else:
            low = min(i.zValue() for i in refs)
            scene._restack(self.items, lambda order: [low - 0.001 * (len(order) - n) for n in range(len(order))],
                           "Au-dessous des objets")
        self.finish()


class ZoomCommand(Command):
    """ZOOM (Z) : Etendue (tout le dessin), Fenêtre (deux coins, par defaut : un premier clic), Précédent, ou un
    facteur (« 2 » = deux fois plus pres, « 0,5 » = deux fois plus loin)."""

    NAME = "ZOOM"
    LABEL = "Zoom"
    REPEATABLE = False

    def start(self):
        self.first = None

    def prompt(self):
        if self.first is not None:
            return Prompt("Spécifiez le coin opposé", [], "point")
        return Prompt("Spécifiez le coin de la fenêtre, entrez un facteur",
                      [("extents", "Etendue", ("E", "ETENDUE", "ÉTENDUE", "EXTENTS")),
                       ("window", "Fenêtre", ("F", "FENETRE", "FENÊTRE", "W", "WINDOW")),
                       ("previous", "Précédent", ("P", "PRECEDENT", "PRÉCÉDENT", "PREVIOUS"))],
                      "point", None, "temps réel", value="count")

    def _view(self):
        return self.ctx.view

    def _remember(self):
        view = self._view()
        center = view.mapToScene(view.viewport().rect().center())
        self.ctx.tool_memory["zoom_previous"] = (view.zoom(), center.x(), center.y())

    def keyword(self, key):
        view = self._view()
        if key == "extents":
            self._remember()
            view.fit_all()
            self.finish()
        elif key == "previous":
            found = self.ctx.tool_memory.get("zoom_previous")
            if found is None:
                self.ctx.message("Aucune vue précédente.", error=True)
            else:
                self._remember()
                view.set_zoom(found[0])
                view.center_on(QPointF(found[1], found[2]))
            self.finish()
        elif key == "window":
            pass

    def value(self, number):
        if number <= 0:
            self.ctx.message("Le facteur doit être positif.", error=True)
            return
        self._remember()
        view = self._view()
        center = view.mapToScene(view.viewport().rect().center())
        view.set_zoom(view.zoom() * number)
        view.center_on(center)
        self.finish()

    def point(self, p):
        if self.first is None:
            self.first = (float(p[0]), float(p[1]))
            return
        (x0, y0), (x1, y1) = self.first, p
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w <= geo.EPS or h <= geo.EPS:
            self.ctx.message("Fenêtre sans épaisseur.", error=True)
            return
        self._remember()
        view = self._view()
        area = view.viewport().rect()
        view.set_zoom(min(area.width() / w, area.height() / h))
        view.center_on(QPointF((x0 + x1) / 2.0, -(y0 + y1) / 2.0))
        self.finish()

    def enter(self):
        self.finish()

    def preview(self, p):
        if self.first is None:
            return []
        (x0, y0), (x1, y1) = self.first, p
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        return [("fence", a, b) for a, b in zip(corners, corners[1:])]


# ==========================================================================
# Registre
# ==========================================================================

NEW_ENTRIES = (
    ("ID", "Coordonnées d'un point", ("ID", "IDPOINT"), IdCommand),
    ("DIST", "Distance", ("DI", "DISTANCE"), DistCommand),
    ("AREA", "Aire", ("AA", "AIRE", "AI"), AreaCommand),
    ("LIST", "Liste", ("LI", "LS", "LISTE"), ListCommand),
    ("DIMCONTINUE", "Cotation continue", ("DCO", "COTCONTINUE", "DIMCONT"), DimContinueCommand),
    ("DIMBASELINE", "Cotation de ligne de base", ("DBA", "COTLIGNEBASE", "DIMBASE"), DimBaselineCommand),
    ("LEADER", "Repère", ("LE", "LEAD", "QLEADER", "REPERE", "REPÈRE", "MLEADER", "MLD"), LeaderCommand),
    ("LENGTHEN", "Allonger", ("LEN", "ALLONGER"), LengthenCommand),
    ("PEDIT", "Modifier une polyligne", ("PE", "PEDIT", "EDITPOLY", "PEDITION"), PeditCommand),
    ("DONUT", "Anneau", ("DO", "DOUGHNUT", "ANNEAU"), DonutCommand),
    ("REVCLOUD", "Nuage de révision", ("NUAGEREV", "REVNUAGE"), RevcloudCommand),
    ("DRAWORDER", "Ordre de tracé", ("DR", "ORDRETRACE", "ORDRE"), DrawOrderCommand),
    ("ZOOM", "Zoom", ("Z",), ZoomCommand),
)


def register(registry, entry_class, by_word):
    for name, label, aliases, factory in NEW_ENTRIES:
        if any(e.name == name for e in registry):
            continue                                    # deja inscrite
        entry = entry_class(name, label, aliases, factory)
        registry.append(entry)
        for word in (name, *aliases):
            by_word.setdefault(word.upper(), entry)



def _self_register():
    """Importe AVANT `cad_commands` : `cad_commands` n'a pas pu l'inscrire (fichier encore incomplet), il le fait ici."""
    from . import cad_commands as _cc
    if hasattr(_cc, "_BY_WORD"):
        register(_cc.REGISTRY, _cc.Entry, _cc._BY_WORD)


_self_register()
