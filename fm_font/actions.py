"""Actions des menus contextuels (canvas, grille) : chaque entrée lance une opération RÉELLE du modèle, en une
étape d'annulation (`canvas.edit` / opérations du projet). Menus = `fm_theme.menu.Menu` (menus de l'appli)."""
from __future__ import annotations

from fontTools.misc.transform import Transform

from . import components, geometry, glyph_info
from . import contours as C


def _nodes(cv):
    glyph = cv.glyph
    return [(c, i) for c, i in sorted(cv.selection) if glyph.contours[c][i].type is not None]


def node_type(cv, kind: str) -> None:
    """kind : corner / smooth / symmetric (nœuds choisis)."""
    nodes = _nodes(cv)

    def fn(glyph):
        for c, i in nodes:
            contour = glyph.contours[c]
            if kind == "corner":
                contour[i].smooth = False
            elif kind == "smooth":
                C.set_smooth(contour, i, True)
            else:
                C.make_symmetric(contour, i)
    cv.edit({"corner": "Nœud en coin", "smooth": "Nœud lisse", "symmetric": "Nœud symétrique"}[kind], fn)


def add_point_at(cv, pos) -> bool:
    hit = cv.hit_segment(pos)
    if hit is None:
        return False
    c, seg, t, _d = hit
    index = {}

    def fn(glyph):
        contour = glyph.contours[c]
        fresh = next(s for s in C.segments(contour) if s[0] == seg[0] and s[2] == seg[2])
        index["i"] = C.insert_point(contour, fresh, t)
    cv.edit("Ajouter un point", fn)
    if "i" in index:
        cv.set_selection({(c, index["i"])})
    return True


def contour_op(cv, op: str) -> None:
    """op : reverse / close / open / start / quadratic / cubic (contours de la sélection)."""
    contours = cv.selected_contours() or list(range(len(cv.glyph.contours)))
    nodes = _nodes(cv)
    tolerance = float(cv.settings["typo_quadratic_tolerance"])

    def fn(glyph):
        for c in contours:
            contour = glyph.contours[c]
            if op == "reverse":
                C.reverse(contour)
            elif op == "close":
                C.close(contour)
            elif op == "quadratic":
                C.contour_to_quadratic(contour, tolerance)
            elif op == "cubic":
                C.contour_to_cubic(contour)
        if op in ("open", "start") and nodes:
            c, i = nodes[0]
            (C.open_at if op == "open" else C.set_start_point)(glyph.contours[c], i)
    labels = {"reverse": "Inverser le sens", "close": "Fermer le contour", "open": "Ouvrir le contour",
              "start": "Point de départ", "quadratic": "Convertir en quadratiques", "cubic": "Convertir en cubiques"}
    cv.edit(labels[op], fn)
    if op in ("open", "start", "quadratic", "cubic"):
        cv.clear_selection()


def glyph_op(cv, op: str) -> None:
    selection = set(cv.selection)
    contours = cv.selected_contours()
    labels = {"overlaps": "Supprimer les chevauchements", "directions": "Corriger le sens", "round": "Arrondir",
              "simplify": "Simplifier", "mirror_h": "Symétrie horizontale", "mirror_v": "Symétrie verticale",
              "union": "Union", "difference": "Différence", "intersection": "Intersection", "xor": "Exclusion",
              "decompose": "Décomposer", "rotate": "Rotation 90°", "scale": "Échelle 110 %",
              "align_left": "Aligner à gauche", "align_right": "Aligner à droite", "align_top": "Aligner en haut",
              "align_bottom": "Aligner en bas", "align_hcenter": "Centrer horizontalement",
              "align_vcenter": "Centrer verticalement", "distribute_h": "Répartir horizontalement",
              "distribute_v": "Répartir verticalement", "center": "Centrer dans la chasse"}
    font = cv.font

    def fn(glyph):
        if op == "overlaps":
            geometry.remove_overlaps(glyph, contours or None)
        elif op == "directions":
            C.correct_directions(glyph)
        elif op == "round":
            geometry.round_coordinates(glyph)
        elif op == "simplify":
            geometry.simplify(glyph)
        elif op in ("mirror_h", "mirror_v"):
            geometry.mirror(glyph, op == "mirror_h", selection or None)
        elif op in geometry.BOOLEAN_OPS:
            if len(contours) >= 2:
                geometry.boolean(glyph, op, contours[:1], contours[1:])
        elif op == "decompose":
            components.decompose(font, glyph, sorted(cv.selected_components) or None)
        elif op in ("rotate", "scale"):
            pts = geometry.selection_points(glyph, geometry.with_handles(glyph, selection)) if selection else \
                [p for c in glyph.contours for p in c]
            b = geometry.bounds_of_points(pts)
            if b is None:
                return
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            m = Transform().rotate(3.141592653589793 / 2) if op == "rotate" else Transform().scale(1.1)
            geometry.transform_glyph(glyph, geometry.around(m, cx, cy), selection or None)
        elif op.startswith("align_"):
            geometry.align(glyph, selection, op[6:])
        elif op.startswith("distribute_"):
            geometry.distribute(glyph, selection, op.endswith("h"))
        elif op == "center":
            from .metrics import center
            center(glyph, font)
    cv.edit(labels[op], fn)
    if op in ("overlaps", "union", "difference", "intersection", "xor", "decompose", "simplify"):
        cv.clear_selection()


def add_anchor(cv, name: str, pos=None) -> None:
    x, y = cv.to_font(pos) if pos is not None else (cv.glyph.width / 2, cv.font.info.capHeight or 700)
    cv.edit(f"Ancre {name}", lambda g: components.set_anchor(g, name, round(x), round(y)))


def canvas_menu(pane, global_pos, local_pos) -> object:
    from fm_theme.menu import Menu
    cv = pane.canvas
    menu = Menu(cv, key="fm_font_canvas")
    has_nodes = bool(_nodes(cv))
    seg = cv.hit_segment(local_pos)
    if seg is not None:
        menu.addAction("Ajouter un point ici").triggered.connect(lambda: add_point_at(cv, local_pos))
    nodes = menu.addMenu("Nœuds")
    nodes.setEnabled(has_nodes)
    for kind, label in (("corner", "Coin"), ("smooth", "Lisse"), ("symmetric", "Symétrique")):
        nodes.addAction(label).triggered.connect(lambda _c=False, k=kind: node_type(cv, k))
    nodes.addAction("Supprimer").triggered.connect(cv.delete_selection)
    contour = menu.addMenu("Contour")
    for op, label in (("reverse", "Inverser le sens"), ("close", "Fermer"), ("open", "Ouvrir au nœud choisi"),
                      ("start", "Point de départ au nœud choisi"), ("quadratic", "Convertir en quadratiques"),
                      ("cubic", "Convertir en cubiques")):
        contour.addAction(label).triggered.connect(lambda _c=False, o=op: contour_op(cv, o))
    paths = menu.addMenu("Tracés")
    for op, label in (("overlaps", "Supprimer les chevauchements"), ("union", "Union (contours choisis)"),
                      ("difference", "Différence (1er moins les autres)"), ("intersection", "Intersection"),
                      ("xor", "Exclusion"), ("directions", "Corriger le sens"), ("simplify", "Simplifier"),
                      ("round", "Arrondir les coordonnées")):
        paths.addAction(label).triggered.connect(lambda _c=False, o=op: glyph_op(cv, o))
    transform = menu.addMenu("Transformer")
    for op, label in (("mirror_h", "Symétrie horizontale"), ("mirror_v", "Symétrie verticale"),
                      ("rotate", "Rotation 90°"), ("scale", "Agrandir de 10 %"), ("center", "Centrer dans la chasse")):
        transform.addAction(label).triggered.connect(lambda _c=False, o=op: glyph_op(cv, o))
    align = menu.addMenu("Aligner / répartir")
    align.setEnabled(len(cv.selection) >= 2)
    for op, label in (("align_left", "À gauche"), ("align_right", "À droite"), ("align_top", "En haut"),
                      ("align_bottom", "En bas"), ("align_hcenter", "Centres horizontaux"),
                      ("align_vcenter", "Centres verticaux"), ("distribute_h", "Répartir horizontalement"),
                      ("distribute_v", "Répartir verticalement")):
        align.addAction(label).triggered.connect(lambda _c=False, o=op: glyph_op(cv, o))
    comp = menu.addMenu("Composants et ancres")
    comp.addAction("Décomposer").triggered.connect(lambda: glyph_op(cv, "decompose"))
    comp.addAction("Ajouter un composant (glyphe choisi dans la grille)…").triggered.connect(
        lambda: pane.add_component_from_grid())
    for name in ("top", "bottom", "_top", "_bottom"):
        comp.addAction(f"Ancre « {name} » ici").triggered.connect(lambda _c=False, n=name: add_anchor(cv, n, local_pos))
    menu.addSeparator()
    menu.addAction("Tout voir").triggered.connect(cv.fit)
    menu.popup(global_pos)
    return menu


def grid_menu(pane, global_pos) -> object:
    from fm_theme.menu import Menu
    grid = pane.grid
    names = grid.selected_names()
    menu = Menu(grid, key="fm_font_grid")
    menu.addAction("Ouvrir dans l'éditeur").triggered.connect(lambda: names and pane.show_glyph(names[0]))
    menu.addAction("Dupliquer").triggered.connect(lambda: pane.duplicate_selected())
    menu.addAction("Supprimer").triggered.connect(lambda: pane.delete_selected())
    menu.addSeparator()
    menu.addAction("Construire les accentués choisis (ancres)").triggered.connect(
        lambda: pane.build_accented([u for n in names for u in pane.project.font[n].unicodes]))
    charsets = menu.addMenu("Créer les glyphes manquants")
    for name in glyph_info.CHARSETS:
        charsets.addAction(name).triggered.connect(lambda _c=False, n=name: pane.create_missing(n))
    menu.addAction("Construire tous les accentués possibles").triggered.connect(
        lambda: pane.build_accented([c for codes in glyph_info.CHARSETS.values() for c in codes]))
    menu.popup(global_pos)
    return menu
