"""Opérations sur le document Design (pages et éléments), chacune = UNE étape d'annulation du board
(`scene.push(avant, après)` : états par identifiant, None = absent). Aucune interface ici."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF

from fm_board import model
from . import design_model as dm, geometry
from .items import DesignElement, DesignPageItem


# ---------------------------------------------------------------- lecture
def pages(scene) -> list[DesignPageItem]:
    return sorted((i for i in scene.board_items() if isinstance(i, DesignPageItem)),
                  key=lambda p: (int(p.data.get("index", 0)), p.y()))


def elements(scene, page=None) -> list[DesignElement]:
    out = [i for i in scene.board_items() if isinstance(i, DesignElement)]
    if page is not None:
        out = [i for i in out if i.data.get("page") == page.item_id]
    return sorted(out, key=lambda i: i.zValue())


def page_rect(page) -> QRectF:
    """Rectangle de l'élément dans les coordonnées de sa page (sans rotation : boîte du contenu)."""
    return QRectF(0, 0, *page.size())


def local_box(item) -> tuple:
    """Enveloppe (x, y, w, h) d'un élément dans sa page (rotation comprise)."""
    r = item.mapRectToParent(item.content_rect())
    return (r.x(), r.y(), r.width(), r.height())


def group_members(scene, item) -> list[DesignElement]:
    group = item.data.get("group") or ""
    if not group:
        return [item]
    return [i for i in elements(scene) if i.data.get("group") == group]


def top_z(scene, page) -> float:
    zs = [i.zValue() for i in elements(scene, page)]
    return (max(zs) + 1.0) if zs else 1.0


# ---------------------------------------------------------------- pages
def _states(scene, items) -> dict:
    return scene.snapshot([i.item_id for i in items])


def relayout(scene, ordered: list) -> None:
    """Pages empilées dans l'ordre donné (index et positions mis à jour, sans annulation : l'appelant l'inclut)."""
    if not ordered:
        return
    origin = (ordered[0].x(), ordered[0].y())
    positions = dm.layout_positions([p.size() for p in ordered], origin)
    for index, (page, (x, y)) in enumerate(zip(ordered, positions)):
        page.data = page.to_dict()
        page.data.update(index=index, x=x, y=y)
        page.apply(page.data)


def add_page(scene, width: float, height: float, after=None, values: dict | None = None,
             origin: QPointF | None = None, text: str = "Ajouter une page") -> DesignPageItem:
    """Nouvelle page (après `after`, sinon à la fin) ; les pages suivantes sont redescendues."""
    scene.commit_live()
    current = pages(scene)
    before = _states(scene, current)
    data = model.new_item(dm.PAGE, w=float(width), h=float(height))
    data.update(values or {})
    if not current:
        at = origin or QPointF(0, 0)
        data["x"], data["y"] = round(at.x() - width / 2, 2), round(at.y() - height / 2, 2)
    page = scene._add(data)
    position = current.index(after) + 1 if after in current else len(current)
    ordered = current[:position] + [page] + current[position:]
    if current:
        ordered[0].data = ordered[0].to_dict()
    relayout(scene, ordered if current else [page])
    before[page.item_id] = None
    scene.push(before, _states(scene, ordered), text)
    return page


def duplicate_page(scene, page) -> DesignPageItem:
    scene.commit_live()
    current = pages(scene)
    before = _states(scene, current)
    data = page.to_dict()
    data["id"] = model.new_id()
    copy_page = scene._add(data)
    position = current.index(page) + 1
    ordered = current[:position] + [copy_page] + current[position:]
    relayout(scene, ordered)
    groups: dict[str, str] = {}
    added = []
    for element in elements(scene, page):
        values = element.to_dict()
        values["id"] = model.new_id()
        values["page"] = copy_page.item_id
        if values.get("group"):
            values["group"] = groups.setdefault(values["group"], model.new_id())
        added.append(scene._add(values))
    before.update({i.item_id: None for i in [copy_page] + added})
    scene.push(before, _states(scene, ordered + added), "Dupliquer la page")
    return copy_page


def delete_page(scene, page) -> None:
    """Supprime la page et ses éléments ; les pages suivantes remontent (une étape)."""
    scene.commit_live()
    current = pages(scene)
    doomed = [page] + elements(scene, page)
    before = _states(scene, current + doomed)
    for item in doomed[1:] + [page]:
        scene._remove(item.item_id)
    rest = [p for p in current if p is not page]
    if rest:
        rest[0].data = rest[0].to_dict()
    relayout(scene, rest)
    after = {i.item_id: None for i in doomed}
    after.update(_states(scene, rest))
    scene.push(before, after, "Supprimer la page")


def move_page(scene, page, index: int) -> None:
    current = pages(scene)
    if page not in current:
        return
    scene.commit_live()
    before = _states(scene, current)
    origin = (current[0].x(), current[0].y())
    ordered = [p for p in current if p is not page]
    index = max(0, min(len(ordered), index))
    ordered.insert(index, page)
    ordered[0].setPos(*origin)
    relayout(scene, ordered)
    scene.push(before, _states(scene, ordered), "Réordonner les pages")


def resize_page(scene, page, width: float, height: float, scale_content: bool = False, fmt: str = "custom"):
    """Nouvelles dimensions de page ; `scale_content` = éléments agrandis / réduits avec elle (proportions gardées,
    centrés)."""
    scene.commit_live()
    current = pages(scene)
    content = elements(scene, page)
    before = _states(scene, current + content)
    w0, h0 = page.size()
    page.data = page.to_dict()
    page.data.update(w=float(width), h=float(height), format=fmt)
    page.apply(page.data)
    if scale_content and content:
        k = min(width / w0, height / h0)
        ox, oy = (width - w0 * k) / 2, (height - h0 * k) / 2
        for item in content:
            scale_element(item, k)
            item.data["x"] = round(item.data["x"] * k + ox, 2)
            item.data["y"] = round(item.data["y"] * k + oy, 2)
            item.apply(item.data)
    relayout(scene, current)
    scene.push(before, _states(scene, current + content), "Redimensionner le design")


def scale_element(item, k: float) -> None:
    """Agrandit `item.data` d'un facteur `k` (taille, texte, contour, arrondi, ombre) ; position inchangée."""
    data = item.data = item.to_dict()
    data["w"] = round(data["w"] * k, 2)
    data["h"] = round(data["h"] * k, 2)
    for key in ("font_size", "stroke_width", "radius"):
        if key in data:
            data[key] = round(float(data[key]) * k, 2)
    shadow = data.get("shadow")
    if isinstance(shadow, dict):
        for key in ("dx", "dy", "blur"):
            shadow[key] = round(float(shadow.get(key, 0.0)) * k, 2)


# ---------------------------------------------------------------- éléments
def add_element(scene, page, kind: str, values: dict, text: str = "Ajouter") -> DesignElement:
    data = model.new_item(kind, page=page.item_id)
    data.update(copy.deepcopy(values))
    data["page"] = page.item_id
    if "x" not in values:
        data["x"] = round((page.size()[0] - data["w"]) / 2, 2)
    if "y" not in values:
        data["y"] = round((page.size()[1] - data["h"]) / 2, 2)
    item = scene.add_new(data, text)
    item.data["z"] = item.zValue()
    return item


def insert_elements(scene, page, dicts: list[dict], offset=(0.0, 0.0), text: str = "Coller") -> list:
    """Copies d'éléments (identifiants et groupes neufs) posées dans `page`, au-dessus des autres, une étape."""
    scene.commit_live()
    z = top_z(scene, page)
    groups: dict[str, str] = {}
    added = []
    for raw in sorted(dicts, key=lambda d: d.get("z", 0.0)):
        data = model.normalize_item(copy.deepcopy(raw))
        if data is None or data["type"] not in dm.ELEMENT_TYPES:
            continue
        data["id"] = model.new_id()
        data["page"] = page.item_id
        data["locked"] = False
        data["x"] = round(float(data["x"]) + offset[0], 2)
        data["y"] = round(float(data["y"]) + offset[1], 2)
        data["z"] = z
        z += 1.0
        if data.get("group"):
            data["group"] = groups.setdefault(data["group"], model.new_id())
        added.append(scene._add(data))
    if added:
        ids = [i.item_id for i in added]
        scene.push({i: None for i in ids}, scene.snapshot(ids), text)
    return added


def change(scene, items, mutate, text: str) -> None:
    """`mutate(item)` modifie `item.data` (place du moment déjà relue) ; une étape."""
    scene.change_items(list(items), mutate, text)


def set_group(scene, items, grouped: bool) -> None:
    items = [i for i in items if isinstance(i, DesignElement)]
    if not items:
        return
    group = model.new_id() if grouped else ""
    change(scene, items, lambda i: i.data.update(group=group), "Grouper" if grouped else "Dissocier")


def align_items(scene, items, mode: str, to_page: bool) -> None:
    items = [i for i in items if isinstance(i, DesignElement) and not i.locked()]
    if not items:
        return
    boxes = [local_box(i) for i in items]
    reference = None
    if to_page or len(items) == 1:
        page = items[0].page_item()
        if page is None:
            return
        reference = (0.0, 0.0) + tuple(page.size())
    targets = dict(zip(items, geometry.align(boxes, mode, reference)))
    _place_boxes(scene, items, boxes, targets, "Aligner")


def distribute_items(scene, items, axis: str) -> None:
    items = [i for i in items if isinstance(i, DesignElement) and not i.locked()]
    if len(items) < 3:
        return
    boxes = [local_box(i) for i in items]
    targets = dict(zip(items, geometry.distribute(boxes, axis)))
    _place_boxes(scene, items, boxes, targets, "Répartir")


def _place_boxes(scene, items, boxes, targets, text):
    shift = {i: (targets[i][0] - b[0], targets[i][1] - b[1]) for i, b in zip(items, boxes)}

    def mutate(item):
        dx, dy = shift[item]
        item.data["x"] = round(item.data["x"] + dx, 2)
        item.data["y"] = round(item.data["y"] + dy, 2)
    change(scene, items, mutate, text)


def restack(scene, items, how: str) -> None:
    """Ordre dans la page : front (premier plan), back (arrière-plan), forward / backward (d'un rang)."""
    items = [i for i in items if isinstance(i, DesignElement)]
    if not items:
        return
    page = items[0].page_item()
    siblings = elements(scene, page) if page is not None else items
    chosen = [i for i in siblings if i in items]
    others = [i for i in siblings if i not in items]
    if how == "front":
        order = others + chosen
    elif how == "back":
        order = chosen + others
    else:
        order = list(siblings)
        indices = [order.index(i) for i in chosen]
        if how == "forward":
            for n in sorted(indices, reverse=True):
                if n + 1 < len(order) and order[n + 1] not in chosen:
                    order[n], order[n + 1] = order[n + 1], order[n]
        else:
            for n in sorted(indices):
                if n - 1 >= 0 and order[n - 1] not in chosen:
                    order[n], order[n - 1] = order[n - 1], order[n]
    z_of = {item: float(n + 1) for n, item in enumerate(order)}
    moved = [i for i in order if i.zValue() != z_of[i]]
    if moved:
        change(scene, moved, lambda i: i.data.update(z=z_of[i]),
               {"front": "Premier plan", "back": "Arrière-plan", "forward": "Avancer", "backward": "Reculer"}[how])


def move_to_page(scene, items, page) -> None:
    """Éléments déposés sur une autre page : rattachés à elle, même place à l'écran (dans l'étape en cours)."""
    for item in items:
        if item.page_item() is page:
            continue
        scene_pos = item.scenePos()
        item.setParentItem(page)
        item.setPos(page.mapFromScene(scene_pos))
        item.data["page"] = page.item_id


def apply_template(scene, template: dict, page=None, after=None, origin: QPointF | None = None):
    """Modèle : sur `page` si elle est vide (redimensionnée, fond repris), sinon sur une nouvelle page après `after` ;
    UNE étape d'annulation (macro)."""
    from . import templates
    scene.commit_live()
    page_values = {"format": "custom", **template.get("page", {})}
    scene.undo.beginMacro(f"Modèle : {template['name']}")
    try:
        if page is not None and not elements(scene, page):
            resize_page(scene, page, template["w"], template["h"], False, "custom")
            change(scene, [page], lambda i: i.data.update(page_values), "Fond de page")
        else:
            page = add_page(scene, template["w"], template["h"], after=after, values=page_values, origin=origin)
        insert_elements(scene, page, templates.element_dicts(template), text="Modèle")
    finally:
        scene.undo.endMacro()
    return page
