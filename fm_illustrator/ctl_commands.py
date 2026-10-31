"""Commandes du contrôleur Illustrator (mélangées à `IllustratorController`) : style, suppression, flèches,
transformations et Transformer de nouveau, alignement, groupe, disposition, verrou, masquer, joindre, tracé
transparent, Pathfinder, vectoriser le contour, aspect et effets, masques, pinceaux, pipette, mode Tracés.
Une étape d'annulation par commande (`self.change`, `scene.replace_items`…)."""
from __future__ import annotations

from fm_board import model as board_model
from . import bezier as bz, layers as lay, model
from .items import IllPathItem


def _split_without(sub: dict, removed: set) -> list[dict]:
    """Sous-tracés restants quand les nœuds `removed` (et leurs segments) disparaissent."""
    nodes = sub["nodes"]
    if not removed:
        return [sub]
    count = len(nodes)
    if sub.get("closed"):
        start = min(removed)
        order = [(start + k) % count for k in range(1, count)]           # après le 1er nœud retiré
    else:
        order = list(range(count))
    runs, run = [], []
    for index in order:
        if index in removed:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(nodes[index])
    if run:
        runs.append(run)
    out = []
    for run in runs:
        if len(run) > 1:
            run[0][2], run[0][3] = run[0][0], run[0][1]                  # extrémités : sans poignée vers le vide
            run[-1][4], run[-1][5] = run[-1][0], run[-1][1]
            out.append({"closed": False, "nodes": run})
    return out


class CommandMixin:
    """Commandes de `IllustratorController` (voir le docstring du fichier)."""

    # -- aspect et effets (appearance.py) --
    def add_effect(self, kind: str):
        from . import appearance as ap
        items = [i for i in self.selection() if ap.effect(i.data, kind) is None]
        if items:
            self.change(items, lambda i: i.data.update(effects=ap.valid_effects(
                list(i.data.get("effects") or []) + [ap.new_effect(kind)])), f"Effet : {ap.LABELS[kind]}")


    def set_effect(self, kind: str, key: str, value):
        """Curseur / couleur d'un effet, EN DIRECT (une étape par geste) ; tous les objets choisis qui l'ont."""
        from . import appearance as ap
        items = [i for i in self.selection() if ap.effect(i.data, kind) is not None]

        def change(item):
            effects = [dict(e) for e in item.data["effects"]]
            for e in effects:
                if e["type"] == kind:
                    e[key] = value
            item.data["effects"] = ap.valid_effects(effects)
        if items:
            self.scene.live_change(f"ill_fx:{kind}:{key}", items, change, f"Effet : {ap.LABELS[kind]}")


    def toggle_effect(self, kind: str):
        from . import appearance as ap
        items = [i for i in self.selection() if ap.effect(i.data, kind) is not None]

        def change(item):
            item.data["effects"] = [dict(e, on=not e.get("on", True)) if e["type"] == kind else e
                                    for e in item.data["effects"]]
        self.change(items, change, "Activer / désactiver l'effet")


    def remove_effect(self, kind: str):
        items = [i for i in self.selection() if any(e["type"] == kind for e in i.data.get("effects") or [])]
        self.change(items, lambda i: i.data.update(effects=[e for e in i.data["effects"] if e["type"] != kind]),
                    "Supprimer l'effet")


    def add_extra_stroke(self):
        from . import appearance as ap
        items = [i for i in self.selection() if len(i.data.get("extra_strokes") or []) < ap.MAX_STROKES]

        def change(item):
            base = dict(ap.STROKE_DEFAULT)
            base["width"] = round(float(item.data.get("stroke_width", 1.0)) * 4 + 4, 3)
            item.data["extra_strokes"] = list(item.data.get("extra_strokes") or []) + [base]
        self.change(items, change, "Ajouter un contour")


    def set_extra_stroke(self, index: int, key: str, value):
        items = [i for i in self.selection() if len(i.data.get("extra_strokes") or []) > index]

        def change(item):
            strokes = [dict(s) for s in item.data["extra_strokes"]]
            strokes[index][key] = value
            item.data["extra_strokes"] = strokes
        if items:
            self.scene.live_change(f"ill_stroke:{index}:{key}", items, change, "Contour supplémentaire")


    def remove_extra_stroke(self, index: int):
        items = [i for i in self.selection() if len(i.data.get("extra_strokes") or []) > index]
        self.change(items, lambda i: i.data.update(
            extra_strokes=[s for n, s in enumerate(i.data["extra_strokes"]) if n != index]), "Supprimer le contour")


    def expand_appearance(self) -> list:
        """Décomposer l'aspect : effets vectoriels appliqués aux nœuds, contours supplémentaires devenus des tracés
        (surfaces, sous l'objet, groupés avec lui) ; les effets tramés restent des effets (ils n'ont pas de forme
        vectorielle : Illustrator les pixellise, non repris). Une étape."""
        from . import appearance as ap, pathfinder as pf
        items = [i for i in self.shapes() if ap.active(i.data, ap.VECTOR) or i.data.get("extra_strokes")]
        if not items:
            return []
        added = []
        for item in items:
            data = item.to_dict()
            subs = ap.render_subpaths(data)
            group = board_model.new_id() if data.get("extra_strokes") else data.get("group", "")
            z = item.zValue()
            for n, stroke in enumerate(data.get("extra_strokes") or []):
                outline = pf.outline_stroke(subs, stroke["width"], data.get("cap", "butt"), data.get("join", "miter"),
                                            float(data.get("miter", 10.0)))
                if outline:
                    added.append(board_model.new_item(
                        model.PATH, x=data["x"], y=data["y"], z=z - 0.5 + n * 0.01, subpaths=outline,
                        fill=stroke["color"], stroke="", opacity=stroke["opacity"] * float(data.get("opacity", 1.0)),
                        layer=data.get("layer", ""), group=group))
            data.update(id=board_model.new_id(), subpaths=subs, extra_strokes=[], group=group,
                        effects=[e for e in data.get("effects") or [] if e["type"] in ap.RASTER])
            added.append(data)
        new = self.scene.replace_items(items, added, "Décomposer l'aspect")
        self.select(new)
        return new


    # -- masques (Objet > Masque d'écrêtage ; panneau Transparence > Créer un masque) --
    def make_mask(self, kind: str = "clip"):
        """L'objet le plus HAUT de la sélection devient le masque des autres (un groupe, une étape). Écrêtage : le
        masque perd sa peinture (comme Illustrator)."""
        items = self.selection()
        if len(items) < 2:
            return
        top = items[-1]
        gid = board_model.new_id()

        def change(item):
            item.data["group"] = gid
            item.data["mask"] = ""
            if item is top:
                item.data["mask"] = kind
                if kind == "clip":
                    item.data.update(fill="", stroke="", fill_gradient=None, stroke_gradient=None)
        self.change(items, change, "Créer un masque d'écrêtage" if kind == "clip" else "Créer un masque d'opacité")
        self.select(items)


    def masked_groups(self) -> list[str]:
        groups = []
        for item in self.selection():
            g = item.data.get("group")
            if g and g in getattr(self.scene, "ill_masks", {}) and g not in groups:
                groups.append(g)
        return groups


    def release_mask(self):
        """Annuler le masque (Ctrl+Alt+7) : les objets ne sont plus groupés ni masqués ; le masque d'écrêtage reste,
        sans peinture (comme Illustrator)."""
        groups = set(self.masked_groups())
        items = [i for i in self.objects() if i.data.get("group") in groups]
        if items:
            self.change(items, lambda i: i.data.update(group="", mask=""), "Annuler le masque")
            self.select(items)


    def invert_opacity_mask(self):
        masks = [self.scene.ill_masks[g] for g in self.masked_groups()
                 if self.scene.ill_masks[g].data.get("mask") == "opacity"]
        if masks:
            self.change(masks, lambda m: m.data.update(mask_invert=not m.data.get("mask_invert")),
                        "Inverser le masque")


    @staticmethod
    def _style_values(key: str, value) -> dict:
        """Une couleur unie remplace le dégradé du même attribut ; un dégradé garde sa 1re couleur comme couleur."""
        values = {key: value}
        if key in ("fill", "stroke"):
            values[f"{key}_gradient"] = None
        elif key in ("fill_gradient", "stroke_gradient") and value:
            values[key[:-len("_gradient")]] = value["stops"][0][1]
        return values


    def set_style(self, key: str, value, text: str = "Style"):
        """Attribut de peinture : sélection (une étape) et style des nouveaux objets."""
        values = self._style_values(key, value)
        self.style.update(values)
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update(values), text)
        self.stateChanged.emit()


    def live_style(self, key: str, value, text: str = "Style"):
        """Pendant un curseur / une couleur glissée : une étape par geste (`scene.commit_live`)."""
        values = self._style_values(key, value)
        self.style.update(values)
        items = self.selection()
        if items:
            self.scene.live_change(f"ill:{key}", items, lambda i: i.data.update(values), text)
        self.stateChanged.emit()


    def document_colors(self) -> list[str]:
        """Couleurs unies des objets (nuancier « du document »), dans l'ordre d'apparition, 18 au plus."""
        out = []
        for item in self.objects():
            for key in ("fill", "stroke"):
                c = item.data.get(key)
                if c and c not in out:
                    out.append(c)
                    if len(out) >= 18:
                        return out
        return out


    def delete_selection(self):
        if any(self.anchors.values()):
            self.delete_anchors()
            return
        board = self.selected_artboard()
        items = self.selection()
        if board is not None and not items:
            self.scene.delete_items([board])
            self.artboard_id = ""
            return
        if items:
            self.scene.delete_items(items)
            self.anchors.clear()


    def delete_anchors(self):
        """Suppr en Sélection directe : les points choisis et leurs segments disparaissent (le tracé s'ouvre ou se
        coupe), comme Illustrator ; un tracé sans segment disparaît."""
        targets = [i for i in self.selection() if self.anchors.get(i.item_id)]
        empty = []

        def cut(item):
            chosen = self.anchors.get(item.item_id, set())
            out = []
            for si, sub in enumerate(item.data["subpaths"]):
                out += _split_without(sub, {ni for s, ni in chosen if s == si})
            item.data["subpaths"] = out
            if not out:
                empty.append(item)
        self.change(targets, cut, "Supprimer des points")
        self.anchors.clear()
        if empty:
            self.scene.delete_items(empty)


    def nudge(self, dx: float, dy: float):
        if any(self.anchors.values()):
            def move(item):
                for si, ni in self.anchors.get(item.item_id, ()):
                    bz.move_node(item.data["subpaths"][si]["nodes"][ni], dx, dy)
            self.change([i for i in self.selection() if self.anchors.get(i.item_id)], move, "Déplacer des points")
            return
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update(x=i.data["x"] + dx, y=i.data["y"] + dy), "Déplacer")


    def transform_selection(self, matrix, text: str, items=None, remember: bool = True):
        """Matrice (repère de la scène) appliquée aux nœuds de chaque objet ; devient la dernière transformation."""
        items = self.selection() if items is None else items

        def apply(item):
            px, py = item.data["x"], item.data["y"]
            item.bake(bz.multiply(bz.multiply(bz.translate(px, py), matrix), bz.translate(-px, -py)))
        self.change(items, apply, text)
        if remember and items:
            self.remember_transform(matrix)


    # -- pinceaux et largeur variable (brushes.py) --
    def set_width_profile(self, profile: list, text: str = "Profil de largeur"):
        from .brushes import valid_profile
        items = [i for i in self.shapes() if i.data.get("stroke")]
        if items:
            value = valid_profile(profile)
            self.change(items, lambda i: i.data.update(width_profile=[list(p) for p in value]), text)


    def set_brush(self, brush: dict | None, live: bool = False):
        """Pointe calligraphique des tracés choisis (None = retirer) ; aussi la pointe courante du Pinceau."""
        from .brushes import valid_brush
        value = valid_brush(brush)
        if value is not None:
            self.brush = dict(value)
        items = [i for i in self.shapes() if i.data.get("stroke")]
        if not items:
            return
        change = lambda i: i.data.update(brush=dict(value) if value else None)   # noqa: E731
        if live:
            self.scene.live_change("ill_brush", items, change, "Pointe calligraphique")
        else:
            self.change(items, change, "Pointe calligraphique" if value else "Retirer le pinceau")


    def remember_transform(self, matrix, copy: bool = False):
        self.last_transform = {"matrix": tuple(matrix), "copy": bool(copy)}


    def transform_again(self):
        """Transformer de nouveau (Ctrl+D) : la dernière transformation (déplacement, rotation, échelle, symétrie)
        refaite sur la sélection ; si c'était une copie déplacée (Ctrl + Alt + glisser), une NOUVELLE copie
        (pas et répétition). Une étape."""
        last = self.last_transform
        items = self.selection()
        if last is None or not items:
            return []
        if last["copy"]:
            dicts = [i.to_dict() for i in items]
            groups = {}
            for d in dicts:
                d["id"] = board_model.new_id()
                if d.get("group"):
                    d["group"] = groups.setdefault(d["group"], board_model.new_id())
                px, py = d["x"], d["y"]
                m = last["matrix"]
                item_m = bz.multiply(bz.multiply(bz.translate(px, py), m), bz.translate(-px, -py))
                d["x"], d["y"] = round(px + item_m[4], 3), round(py + item_m[5], 3)
            new = self.scene.replace_items([], dicts, "Transformer de nouveau")
            self.select(new)
            return new
        self.transform_selection(last["matrix"], "Transformer de nouveau")
        return items


    def move_dialog(self):
        """Objet > Transformer > Déplacer… : « dx, dy » en unités."""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self.pane, "Déplacer", "Déplacement horizontal, vertical (unités) :",
                                        text="10, 0")
        if not ok:
            return
        try:
            dx, dy = (float(v.replace(" ", "")) for v in text.replace(";", ",").split(",")[:2])
        except ValueError:
            return
        self.transform_selection(bz.translate(dx, dy), "Déplacer")


    def align(self, how: str):
        from .tools_xform import align
        align(self, how)


    def distribute(self, axis: str, spacing: bool = False):
        from .tools_xform import distribute
        distribute(self, axis, spacing)


    def toggle_smart_guides(self):
        self.smart_guides = not self.smart_guides
        self.stateChanged.emit()


    def flip(self, horizontal: bool):
        rect = self.selection_rect()
        if rect is None:
            return
        c = rect.center()
        m = bz.scale(-1, 1, c.x(), c.y()) if horizontal else bz.scale(1, -1, c.x(), c.y())
        self.transform_selection(m, "Symétrie")


    def rotate_selection(self, degrees: float):
        rect = self.selection_rect()
        if rect is not None:
            self.transform_selection(bz.rotate(degrees, rect.center().x(), rect.center().y()), "Rotation")


    def set_group(self, grouped: bool):
        items = self.selection()
        if not items:
            return
        gid = board_model.new_id() if grouped else ""
        self.change(items, lambda i: i.data.update(group=gid), "Grouper" if grouped else "Dissocier")


    def arrange(self, how: str):
        """Disposition DANS le calque de chaque objet : « front » (Ctrl+Maj+]), « forward » (Ctrl+]),
        « backward » (Ctrl+[), « back » (Ctrl+Maj+[)."""
        items = self.selection()
        if not items:
            return
        objects = self.objects()
        z_of = {}
        by_layer: dict = {}
        for item in items:
            by_layer.setdefault(id(lay.layer_of(self.scene, item)), []).append(item)
        for chosen in by_layer.values():
            layer = lay.layer_of(self.scene, chosen[0])
            stack = lay.members(self.scene, layer, objects) if layer is not None else list(objects)
            stack.sort(key=lambda i: i.zValue())
            rest = [i for i in stack if i not in chosen]
            if how == "front":
                order = rest + chosen
            elif how == "back":
                order = chosen + rest
            else:
                order = list(stack)
                step = 1 if how == "forward" else -1
                for item in (reversed(chosen) if step > 0 else chosen):
                    k = order.index(item)
                    j = k + step
                    if 0 <= j < len(order) and order[j] not in chosen:
                        order[k], order[j] = order[j], order[k]
            base = (lay.band_base(layer) + 1) if layer is not None else min(i.zValue() for i in stack)
            for n, item in enumerate(order):
                if item.zValue() != base + n:
                    z_of[item.item_id] = base + n
        targets = [i for i in objects if i.item_id in z_of]
        if targets:
            self.change(targets, lambda i: i.data.update(z=z_of[i.item_id]), "Disposition")
        self.refresh()


    # -- Pathfinder (pathfinder.py) --
    @staticmethod
    def scene_subpaths(item) -> list:
        subs = bz.copy_subpaths(item.data["subpaths"])
        bz.transform(subs, bz.translate(item.data["x"], item.data["y"]))
        return subs


    PATHFINDER = {"unite": "Réunion", "minus_front": "Soustraction", "intersect": "Intersection",
                  "exclude": "Exclusion", "divide": "Division", "trim": "Découpe", "merge": "Fusion",
                  "crop": "Recadrage", "minus_back": "Soustraction arrière"}


    def pathfinder(self, mode: str) -> list:
        """Panneau Pathfinder : les objets choisis (du plus bas au plus haut) remplacés par le résultat (une étape).
        Modes de forme : style du plus haut (Soustraction : du plus bas) ; Division / Découpe / Fusion /
        Recadrage : chaque morceau garde le style de son objet, morceaux groupés ; Découpe, Fusion et Recadrage
        retirent les contours."""
        from . import pathfinder as pf
        from .tools_draw import place_origin
        items = self.shapes()
        if len(items) < 2:
            return []
        shapes = [(self.scene_subpaths(i), i.data.get("fill_rule", "nonzero")) for i in items]
        if mode in ("unite", "minus_front", "intersect", "exclude", "minus_back"):
            subs = pf.combine(shapes, mode)
            source = items[0] if mode == "minus_front" else items[-1]
            results = [(source, subs)] if subs else []
        elif mode == "divide":
            results = [(items[o], s) for o, s in pf.divide(shapes)]
        elif mode == "trim":
            results = [(items[o], s) for o, s in pf.trim(shapes)]
        elif mode == "merge":
            results = [(items[o], s) for o, s in pf.merge(shapes, [i.data.get("fill") or "" for i in items])]
        elif mode == "crop":
            results = [(items[o], s) for o, s in pf.crop(shapes)]
        else:
            raise ValueError(mode)
        group = board_model.new_id() if len(results) > 1 else ""
        z = max(i.zValue() for i in items)
        added = []
        for n, (source, subs) in enumerate(results):
            subs, origin = place_origin(subs)
            data = source.to_dict()
            data.update(id=board_model.new_id(), subpaths=subs, x=origin.x(), y=origin.y(), group=group,
                        z=z - len(results) + 1 + n, fill_rule="nonzero")
            if mode in ("trim", "merge", "crop"):
                data["stroke"] = ""
                data["stroke_gradient"] = None
            added.append(data)
        new = self.scene.replace_items(items, added, self.PATHFINDER[mode])
        self.select(new)
        return new


    def outline_stroke(self) -> list:
        """Vectoriser le contour : le contour de chaque objet choisi devient une surface (couleur du contour) ; un
        objet qui a aussi un fond garde son fond dessous (les deux groupés)."""
        from . import pathfinder as pf
        from .tools_draw import place_origin
        items = [i for i in self.shapes() if i.data.get("stroke") and float(i.data.get("stroke_width", 0)) > 0]
        if not items:
            return []
        added = []
        from . import brushes
        for item in items:
            if brushes.has_brush(item.data):                # largeur variable : la surface calculée, nettoyée
                shape = brushes.outline(dict(item.data, subpaths=self.scene_subpaths(item)))
                subs = pf.combine([(shape, "nonzero")], "unite") if shape else []
            else:
                subs = pf.outline_stroke(self.scene_subpaths(item), float(item.data["stroke_width"]),
                                         item.data.get("cap", "butt"), item.data.get("join", "miter"),
                                         float(item.data.get("miter", 10.0)))
            if not subs:
                continue
            subs, origin = place_origin(subs)
            group = board_model.new_id() if item.data.get("fill") else item.data.get("group", "")
            if item.data.get("fill"):
                base = item.to_dict()
                base.update(id=board_model.new_id(), stroke="", stroke_gradient=None, group=group)
                added.append(base)
            outline = item.to_dict()
            outline.update(id=board_model.new_id(), subpaths=subs, x=origin.x(), y=origin.y(),
                           fill=item.data["stroke"], fill_gradient=item.data.get("stroke_gradient"),
                           stroke="", stroke_gradient=None, fill_rule="nonzero", group=group,
                           z=item.zValue() + 0.5, width_profile=[], brush=None)
            added.append(outline)
        new = self.scene.replace_items(items, added, "Vectoriser le contour")
        self.select(new)
        return new


    def lock_selection(self):
        items = self.selection()
        if items:
            self.scene.clearSelection()
            self.scene.change_items(items, lambda i: i.data.update(locked=True), "Verrouiller")


    def unlock_all(self):
        locked = [i for i in self.objects() if i.locked()]
        if locked:
            self.scene.change_items(locked, lambda i: i.data.update(locked=False), "Tout déverrouiller",
                                    include_locked=True)
            self.select(locked)


    def hide_selection(self):
        items = self.selection()
        if items:
            self.scene.clearSelection()
            self.change(items, lambda i: i.data.update(hidden=True), "Masquer")


    def show_all(self):
        hidden = [i for i in self.objects() if i.data.get("hidden")]
        if hidden:
            self.change(hidden, lambda i: i.data.update(hidden=False), "Tout afficher")
            self.select(hidden)


    def join_selection(self):
        """Joindre (Ctrl+J) : relie les deux extrémités ouvertes les plus proches de la sélection (deux tracés
        ouverts, ou un tracé ouvert qui se ferme)."""
        items = [i for i in self.shapes() if any(not s["closed"] for s in i.data["subpaths"])]
        if len(items) == 1:
            def close(item):
                for sub in item.data["subpaths"]:
                    if not sub["closed"] and len(sub["nodes"]) > 1:
                        sub["closed"] = True
                        bz.close_if_touching({"closed": False, "nodes": sub["nodes"]}, 0.01)
                        break
            self.change(items, close, "Joindre")
            return
        if len(items) != 2:
            return
        a, b = items
        best = None
        for ia, sa in enumerate(a.data["subpaths"]):
            if sa["closed"]:
                continue
            for ib, sb in enumerate(b.data["subpaths"]):
                if sb["closed"]:
                    continue
                for a_end in (True, False):
                    for b_start in (True, False):
                        na = sa["nodes"][-1 if a_end else 0]
                        nb = sb["nodes"][0 if b_start else -1]
                        d = (na[0] + a.data["x"] - nb[0] - b.data["x"]) ** 2 + \
                            (na[1] + a.data["y"] - nb[1] - b.data["y"]) ** 2
                        if best is None or d < best[0]:
                            best = (d, ia, ib, a_end, b_start)
        if best is None:
            return
        _d, ia, ib, a_end, b_start = best
        moved = bz.copy_subpaths([b.data["subpaths"][ib]])
        bz.transform(moved, bz.translate(b.data["x"] - a.data["x"], b.data["y"] - a.data["y"]))
        joined = bz.join(a.data["subpaths"][ia], moved[0], a_end, b_start)
        rest_b = [s for k, s in enumerate(b.data["subpaths"]) if k != ib]
        new_a = a.to_dict()
        new_a["id"] = board_model.new_id()          # remplacés : identifiants neufs (annulation de replace_items)
        new_a["subpaths"] = [joined if k == ia else s for k, s in enumerate(a.data["subpaths"])]
        added = [new_a]
        if rest_b:
            new_b = b.to_dict()
            new_b.update(id=board_model.new_id(), subpaths=rest_b)
            added.append(new_b)
        result = self.scene.replace_items([a, b], added, "Joindre")
        self.select(result[:1])


    def make_compound(self, compound: bool):
        """Tracé transparent (Ctrl+8) : les sous-tracés des objets choisis en UN objet (style du plus haut), règle
        pair-impair ; Ctrl+Alt+Maj+8 = défaire en un objet par sous-tracé."""
        items = self.shapes()
        if compound and len(items) > 1:
            top = items[-1]
            subs = []
            for item in items:
                moved = bz.copy_subpaths(item.data["subpaths"])
                bz.transform(moved, bz.translate(item.data["x"] - top.data["x"], item.data["y"] - top.data["y"]))
                subs += moved
            data = top.to_dict()
            data.update(id=board_model.new_id(), subpaths=subs, fill_rule="evenodd", group="")
            self.select(self.scene.replace_items(items, [data], "Tracé transparent"))
        elif not compound:
            parts = [i for i in items if len(i.data["subpaths"]) > 1]
            added = []
            for item in parts:
                for sub in item.data["subpaths"]:
                    data = item.to_dict()
                    data.update(subpaths=[sub], id=board_model.new_id(), fill_rule="nonzero")
                    added.append(data)
            if parts:
                self.select(self.scene.replace_items(parts, added, "Défaire le tracé transparent"))


    def copy_style(self):
        items = self.selection()
        if items:
            self.style_clipboard = model.style_of(items[-1].data)


    def paste_style(self):
        style = self.style_clipboard
        if style and self.selection():
            self.change(self.selection(), lambda i: i.data.update(style), "Coller le style")


    def eyedrop(self, source: IllPathItem):
        """Pipette (I) : le style de `source` va à la sélection et devient le style courant."""
        style = model.style_of(source.data)
        self.style.update(style)
        targets = [i for i in self.selection() if i is not source]
        if targets:
            self.change(targets, lambda i: i.data.update(style), "Pipette")
        self.stateChanged.emit()


    def swap_fill_stroke(self):
        """Maj+X : intervertit fond et contour (sélection et style courant)."""
        self.style["fill"], self.style["stroke"] = self.style["stroke"], self.style["fill"]
        items = self.selection()
        if items:
            self.change(items, lambda i: i.data.update(fill=i.data["stroke"], stroke=i.data["fill"]),
                        "Intervertir fond et contour")
        self.stateChanged.emit()


    def default_colors(self):
        """D : fond blanc, contour noir 1 pt."""
        values = {"fill": model.DEFAULT_FILL, "stroke": model.DEFAULT_STROKE, "stroke_width": 1.0}
        self.style.update(values)
        if self.selection():
            self.change(self.selection(), lambda i: i.data.update(values), "Couleurs par défaut")
        self.stateChanged.emit()


    def set_none(self):
        """/ : aucun pour l'attribut au premier plan (fond ou contour)."""
        self.set_style(self.focus, "", "Aucun")


    def toggle_outline(self):
        """Mode Tracés (Ctrl+Y) : contours fins sans peinture (affichage seulement)."""
        self.scene.ill_outline = not bool(getattr(self.scene, "ill_outline", False))
        for item in self.objects():
            item.update()
        self.stateChanged.emit()
