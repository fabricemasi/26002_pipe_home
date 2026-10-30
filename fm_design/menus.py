"""Menus du module Design (barre contextuelle, clic droit, export) : couleurs (palette, couleurs du document,
sélecteur des réglages), fond et dégradés, contour, curseurs en direct (une étape d'annulation par geste), ombre,
position (ordre, alignement, répartition), masque d'image, effets du texte, police, taille, réglages et filtres
d'image, retournement, redimensionnement du design, export. Briques : `settings_menu.Menu` / `menu_row`, champs des
réglages."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QVBoxLayout, QWidget

from fm_board.ui import FontPicker, _GlyphButton, _menu, _slider, _SwatchGrid
from . import design_model as dm, document as doc
from .items import DesignImageItem, DesignShapeItem


def _popup(ctl, menu, anchor):
    menu.aboutToHide.connect(ctl.scene.commit_live)
    menu.aboutToHide.connect(ctl.ui.schedule_sync)
    if isinstance(anchor, QWidget):
        menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))
    else:
        menu.popup(anchor)


def _live(ctl, key, items, change, text):
    ctl.scene.live_change(key, items, change, text)


# ---------------------------------------------------------------- menus de propriétés
def color_menu(ctl, anchor, items, key, label, allow_none=False, after=None):
    """Palette + « Autre couleur… » (sélecteur des réglages, aperçu en direct, une étape)."""
    from settings_menu import menu_row
    menu = _menu(ctl.pane, f"design_{key}")
    current = items[0].data.get(key) if items else None
    grid = _SwatchGrid(dm.PALETTE, current, 6)

    def pick(color):
        menu.close()
        doc.change(ctl.scene, items, lambda i: (i.data.update({key: color}), after and after(i)), label)
    grid.picked.connect(pick)
    menu_row(menu, label, grid)
    used = ctl.document_colors()
    if used:
        mine = _SwatchGrid(used, current, 6)
        mine.picked.connect(pick)
        menu_row(menu, "Du document", mine)
    if allow_none:
        none = menu.addAction("Aucune")
        none.triggered.connect(lambda: doc.change(ctl.scene, items, lambda i: i.data.update({key: ""}), label))
    other = menu.addAction("Autre couleur…")
    other.triggered.connect(lambda: QTimer.singleShot(0, lambda: custom_color(ctl, anchor, items, key, label,
                                                                             current)))
    _popup(ctl, menu, anchor)


def custom_color(ctl, anchor, items, key, label, current, setter=None):
    from settings_widgets import _ColorPickerPopup
    popup = _ColorPickerPopup(current if isinstance(current, str) and current.startswith("#") else "#ffffff",
                              label, ctl.pane)
    apply = setter or (lambda i, c: i.data.update({key: c}))
    live_key = f"design_color:{key}"
    popup.colorChanged.connect(lambda c: _live(ctl, live_key, items, lambda i: apply(i, c), label))

    def commit(c):
        _live(ctl, live_key, items, lambda i: apply(i, c), label)
        ctl.scene.commit_live()
        ctl.ui.schedule_sync()

    def cancel():
        had = ctl.scene._live is not None and ctl.scene._live[0] == live_key
        ctl.scene.commit_live()
        if had:
            ctl.scene.undo.undo()
    popup.committed.connect(commit)
    popup.cancelled.connect(cancel)
    popup.show_near(anchor if isinstance(anchor, QWidget) else ctl.pane)


def fill_menu(ctl, anchor, items, prefix=("fill", "fill_type", "fill2", "gradient_angle"), label="Fond"):
    """Fond : couleur, type (uni, dégradé linéaire / radial, aucun), 2e couleur et angle du dégradé."""
    from settings_menu import menu_row
    color_key, type_key, second_key, angle_key = prefix
    menu = _menu(ctl.pane, f"design_{color_key}")
    first = items[0].data if items else {}
    kind = first.get(type_key, "solid")

    def set_color(key):
        def pick(color):
            menu.close()

            def change(i):
                i.data[key] = color
                if i.data.get(type_key) == "none":
                    i.data[type_key] = "solid"
            doc.change(ctl.scene, items, change, label)
        return pick
    grid = _SwatchGrid(dm.PALETTE, first.get(color_key), 6)
    grid.picked.connect(set_color(color_key))
    menu_row(menu, "Couleur", grid)
    used = ctl.document_colors()
    if used:
        mine = _SwatchGrid(used, first.get(color_key), 6)
        mine.picked.connect(set_color(color_key))
        menu_row(menu, "Du document", mine)
    for value, text in (("solid", "Uni"), ("linear", "Dégradé linéaire"), ("radial", "Dégradé radial"),
                        ("none", "Aucun (transparent)")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(kind == value)
        action.triggered.connect(lambda _c=False, v=value: doc.change(ctl.scene, items,
                                                                       lambda i: i.data.update({type_key: v}), label))
    if kind in ("linear", "radial"):
        grid2 = _SwatchGrid(dm.PALETTE, first.get(second_key), 6)
        grid2.picked.connect(set_color(second_key))
        menu_row(menu, "2e couleur", grid2)
        if kind == "linear":
            angle = _slider(0, 359, round(float(first.get(angle_key, 90.0))), "°")
            angle.valueChanged.connect(lambda v: _live(ctl, f"design_{angle_key}", items,
                                                       lambda i: i.data.update({angle_key: float(v)}), "Angle"))
            menu_row(menu, "Angle", angle)
    other = menu.addAction("Autre couleur…")
    other.triggered.connect(lambda: QTimer.singleShot(0, lambda: custom_color(
        ctl, anchor, items, color_key, label, first.get(color_key),
        lambda i, c: i.data.update({color_key: c, type_key: "solid" if i.data.get(type_key) == "none"
                                    else i.data.get(type_key)}))))
    _popup(ctl, menu, anchor)


def stroke_menu(ctl, anchor, items):
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_stroke")
    first = items[0].data
    grid = _SwatchGrid(dm.PALETTE, first.get("stroke"), 6)

    def pick(color):
        menu.close()

        def change(i):
            i.data["stroke"] = color
            if float(i.data.get("stroke_width", 0.0)) <= 0:
                i.data["stroke_width"] = 4.0
        doc.change(ctl.scene, items, change, "Couleur du contour")
    grid.picked.connect(pick)
    menu_row(menu, "Couleur", grid)
    width = _slider(0, 100, round(float(first.get("stroke_width", 0.0))))
    width.valueChanged.connect(lambda v: _live(ctl, "design_stroke_width", items,
                                               lambda i: i.data.update(stroke_width=float(v)), "Épaisseur"))
    menu_row(menu, "Épaisseur", width)
    shapes = [i for i in items if isinstance(i, DesignShapeItem)]
    if shapes:
        for value, text in (("solid", "Trait plein"), ("dashed", "Tirets"), ("dotted", "Pointillés")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(first.get("stroke_style", "solid") == value)
            action.triggered.connect(lambda _c=False, v=value: doc.change(
                ctl.scene, shapes, lambda i: i.data.update(stroke_style=v), "Style du contour"))
    rounded = [i for i in items if isinstance(i, DesignImageItem)
               or (isinstance(i, DesignShapeItem) and i.data.get("shape") in dm.RADIUS_SHAPES)]
    if rounded:
        bound = int(min(min(i.size()) / 2 for i in rounded))
        radius = _slider(0, max(1, bound), min(bound, round(float(rounded[0].data.get("radius", 0.0)))))
        radius.valueChanged.connect(lambda v: _live(ctl, "design_radius", rounded,
                                                    lambda i: i.data.update(radius=float(v)), "Arrondi des angles"))
        menu_row(menu, "Arrondi", radius)
    lines = [i for i in shapes if i.data.get("shape") == "line"]
    if lines:
        for end, text in (("cap_start", "Début"), ("cap_end", "Fin")):
            sub = menu.addMenu(f"Extrémité : {text.lower()}")
            for value, name in (("none", "Aucune"), ("arrow", "Flèche"), ("filled", "Flèche pleine"),
                                ("circle", "Rond")):
                action = sub.addAction(name)
                action.setCheckable(True)
                action.setChecked(lines[0].data.get(end, "none") == value)
                action.triggered.connect(lambda _c=False, e=end, v=value: doc.change(
                    ctl.scene, lines, lambda i: i.data.update({e: v}), "Extrémité"))
    _popup(ctl, menu, anchor)


def slider_menu(ctl, anchor, items, rows, key, title):
    """Menu de curseurs : rows = [(clé, libellé, min, max, facteur, unité)] ; une étape par geste."""
    from settings_menu import menu_row
    menu = _menu(ctl.pane, key)
    first = items[0].data
    for field, label, low, high, factor, unit in rows:
        value = first.get(field, 0.0)
        slider = _slider(low, high, round(float(value) * factor), unit)
        slider.valueChanged.connect(lambda v, f=field, k=factor: _live(
            ctl, f"design_{f}", items, lambda i: i.data.update({f: v / k}), title))
        menu_row(menu, label, slider)
    return menu


def shadow_menu(ctl, anchor, items):
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_shadow")
    first = dict(items[0].data.get("shadow") or dm.SHADOW)
    toggle = menu.addAction("Ombre portée")
    toggle.setCheckable(True)
    toggle.setChecked(bool(first.get("enabled")))

    def set_shadow(**values):
        def change(i):
            shadow = dict(i.data.get("shadow") or dm.SHADOW)
            shadow.update(values)
            i.data["shadow"] = shadow
        return change
    toggle.triggered.connect(lambda on: doc.change(ctl.scene, items, set_shadow(enabled=bool(on)), "Ombre"))
    for field, label, low, high in (("blur", "Flou", 0, 120), ("dx", "Décalage X", -100, 100),
                                    ("dy", "Décalage Y", -100, 100)):
        slider = _slider(low, high, round(float(first.get(field, 0.0))))
        slider.valueChanged.connect(lambda v, f=field: _live(ctl, f"design_shadow_{f}", items,
                                                             set_shadow(enabled=True, **{f: float(v)}), "Ombre"))
        menu_row(menu, label, slider)
    alpha = QColor(first.get("color", "#59000000")).alpha()
    opacity = _slider(0, 100, round(alpha / 2.55), "%")

    def set_alpha(v):
        def change(i):
            shadow = dict(i.data.get("shadow") or dm.SHADOW)
            color = QColor(shadow.get("color", "#59000000"))
            color.setAlpha(round(v * 2.55))
            shadow.update(enabled=True, color=color.name(QColor.HexArgb))
            i.data["shadow"] = shadow
        return change
    opacity.valueChanged.connect(lambda v: _live(ctl, "design_shadow_alpha", items, set_alpha(v), "Ombre"))
    menu_row(menu, "Opacité", opacity)
    grid = _SwatchGrid(dm.PALETTE, None, 6)

    def pick(color):
        def change(i):
            shadow = dict(i.data.get("shadow") or dm.SHADOW)
            c = QColor(color)
            c.setAlpha(QColor(shadow.get("color", "#59000000")).alpha())
            shadow.update(enabled=True, color=c.name(QColor.HexArgb))
            i.data["shadow"] = shadow
        doc.change(ctl.scene, items, change, "Ombre")
    grid.picked.connect(pick)
    menu_row(menu, "Couleur", grid)
    _popup(ctl, menu, anchor)


def position_menu(ctl, anchor, items):
    menu = _menu(ctl.pane, "design_position")
    for how, text in (("front", "Premier plan (Ctrl+Alt+])"), ("forward", "Avancer (Ctrl+])"),
                      ("backward", "Reculer (Ctrl+[)"), ("back", "Arrière-plan (Ctrl+Alt+[)")):
        menu.addAction(text).triggered.connect(lambda _c=False, h=how: doc.restack(ctl.scene, items, h))
    menu.addSeparator()
    to_page = len(items) == 1
    for mode, text in (("left", "Aligner à gauche"), ("hcenter", "Centrer"), ("right", "Aligner à droite"),
                       ("top", "Aligner en haut"), ("vcenter", "Milieu"), ("bottom", "Aligner en bas")):
        suffix = " (page)" if to_page else ""
        menu.addAction(text + suffix).triggered.connect(
            lambda _c=False, m=mode: doc.align_items(ctl.scene, items, m, to_page))
    if len(items) > 1:
        sub = menu.addMenu("Aligner sur la page")
        for mode, text in (("left", "Gauche"), ("hcenter", "Centre"), ("right", "Droite"), ("top", "Haut"),
                           ("vcenter", "Milieu"), ("bottom", "Bas")):
            sub.addAction(text).triggered.connect(lambda _c=False, m=mode: doc.align_items(ctl.scene, items, m, True))
    if len(items) > 2:
        menu.addSeparator()
        menu.addAction("Répartir horizontalement").triggered.connect(
            lambda: doc.distribute_items(ctl.scene, items, "h"))
        menu.addAction("Répartir verticalement").triggered.connect(
            lambda: doc.distribute_items(ctl.scene, items, "v"))
    _popup(ctl, menu, anchor)


def open_context_menu(ctl, global_pos):
    """Clic droit dans une page."""
    menu = _menu(ctl.pane, "design_context")
    items = ctl.selection()
    if items:
        menu.addAction("Copier (Ctrl+C)").triggered.connect(ctl.copy)
        menu.addAction("Couper (Ctrl+X)").triggered.connect(lambda: (ctl.copy(), ctl.scene.delete_items(items)))
    menu.addAction("Coller (Ctrl+V)").triggered.connect(ctl.paste)
    if items:
        menu.addAction("Dupliquer (Ctrl+D)").triggered.connect(ctl.duplicate)
        menu.addAction("Copier le style (Ctrl+Alt+C)").triggered.connect(ctl.copy_style)
        if getattr(ctl, "style_clipboard", None):
            menu.addAction("Coller le style (Ctrl+Alt+V)").triggered.connect(ctl.paste_style)
        menu.addAction("Supprimer (Suppr)").triggered.connect(lambda: ctl.scene.delete_items(items))
        menu.addSeparator()
        grouped = len(items) > 1 and len({i.data.get("group") for i in items}) == 1 and items[0].data.get("group")
        if len(items) > 1:
            if grouped:
                menu.addAction("Dissocier (Ctrl+Maj+G)").triggered.connect(lambda: doc.set_group(ctl.scene, items, False))
            else:
                menu.addAction("Grouper (Ctrl+G)").triggered.connect(lambda: doc.set_group(ctl.scene, items, True))
        locked = all(i.locked() for i in items)
        menu.addAction("Déverrouiller" if locked else "Verrouiller (Alt+Maj+L)").triggered.connect(ctl.toggle_lock)
        if len(items) == 1:
            menu.addAction("Renommer le calque…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: rename_layer(ctl, items[0])))
        order = menu.addMenu("Ordre")
        for how, text in (("front", "Premier plan"), ("forward", "Avancer"), ("backward", "Reculer"),
                          ("back", "Arrière-plan")):
            order.addAction(text).triggered.connect(lambda _c=False, h=how: doc.restack(ctl.scene, items, h))
        images = [i for i in items if isinstance(i, DesignImageItem)]
        if len(images) == 1:
            menu.addAction("Recadrer").triggered.connect(lambda: ctl.start_crop(images[0]))
            menu.addAction("Remplacer l'image…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: replace_image_dialog(ctl, images[0])))
            menu.addAction("Définir comme arrière-plan de la page").triggered.connect(
                lambda: set_page_background_image(ctl, images[0]))
    page = ctl.current_page()
    if page is not None:
        menu.addSeparator()
        menu.addAction("Couleur de la page…").triggered.connect(
            lambda: QTimer.singleShot(0, lambda: fill_menu(ctl, ctl.ui.context, [page],
                                                           ("background", "bg_type", "bg2", "bg_angle"), "Fond de page")))
        guides = menu.addMenu("Repères et marges")
        w, h = page.size()
        guides.addAction("Ajouter un repère vertical (centre)").triggered.connect(
            lambda: add_guide(ctl, page, "v", w / 2))
        guides.addAction("Ajouter un repère horizontal (milieu)").triggered.connect(
            lambda: add_guide(ctl, page, "h", h / 2))
        if page.data.get("guides"):
            guides.addAction("Retirer tous les repères").triggered.connect(lambda: doc.change(
                ctl.scene, [page], lambda i: i.data.update(guides=[]), "Repères"))
        rulers = guides.addAction("Règles (Maj+R)")
        rulers.setCheckable(True)
        rulers.setChecked(ctl.rulers.visible)
        rulers.triggered.connect(lambda on: ctl.rulers.set_visible(bool(on)))
        margins = guides.addAction("Afficher les marges")
        margins.setCheckable(True)
        margins.setChecked(bool(page.data.get("margins")))
        margins.triggered.connect(lambda on: doc.change(ctl.scene, [page], lambda i: i.data.update(margins=bool(on)),
                                                        "Marges"))
        if page.data.get("bg_asset"):
            menu.addAction("Retirer l'image d'arrière-plan").triggered.connect(
                lambda: doc.change(ctl.scene, [page], lambda i: i.data.update(bg_asset=""), "Arrière-plan"))
    menu.addSeparator()
    menu.addAction("Raccourcis clavier (?)…").triggered.connect(lambda: QTimer.singleShot(0, lambda: show_shortcuts(ctl)))
    menu.aboutToHide.connect(ctl.scene.commit_live)
    menu.popup(global_pos)


SHORTCUTS = [
    ("Ctrl + glisser", "déplacer (Ctrl + Alt + glisser : une copie) ; sans Ctrl : cadre de sélection"),
    ("Clic / Maj + clic", "choisir / ajouter à la sélection"),
    ("Double-clic", "modifier un texte, recadrer une image"),
    ("T, R, C, L", "texte, rectangle, cercle, ligne"),
    ("Suppr", "supprimer"), ("Ctrl+C / X / V", "copier, couper, coller"), ("Ctrl+D", "dupliquer"),
    ("Ctrl+Alt+C / V", "copier / coller le style"), ("Ctrl+A", "tout choisir dans la page"),
    ("Ctrl+G / Ctrl+Maj+G", "grouper / dissocier"), ("Alt+Maj+L", "verrouiller"),
    ("Ctrl+] / [  (Alt : extrême)", "avancer / reculer (premier plan / arrière-plan)"),
    ("Flèches (Maj : ×10)", "décaler de 1 px"), ("PageUp / PageDown", "page précédente / suivante"),
    ("Ctrl+B / I / U", "gras, italique, souligné"), ("Ctrl+Maj+K", "majuscules"),
    ("Ctrl+Maj+L / E / R / J", "aligner le texte : gauche, centre, droite, justifié"),
    ("Ctrl+Maj+> / <", "taille du texte"), ("Maj+R", "règles (tirer un repère depuis une règle)"),
    ("Ctrl+Alt+P", "présenter en plein écran"), ("Ctrl+Z / Ctrl+Y", "annuler / rétablir"),
    ("Molette, bouton du milieu, Espace", "zoomer, se déplacer dans le board"),
]


def show_shortcuts(ctl):
    from PySide6.QtWidgets import QMessageBox
    text = "\n".join(f"{keys} : {what}" for keys, what in SHORTCUTS)
    QMessageBox.information(ctl.pane, "Module Design : raccourcis", text)


def rename_layer(ctl, item):
    name, ok = QInputDialog.getText(ctl.pane, "Renommer le calque", "Nom (vide = nom automatique) :",
                                    text=item.data.get("name", ""))
    if ok:
        doc.change(ctl.scene, [item], lambda i: i.data.update(name=name.strip()), "Renommer le calque")


def add_guide(ctl, page, axis, pos):
    doc.change(ctl.scene, [page], lambda i: i.data.update(
        guides=list(i.data.get("guides") or []) + [{"axis": axis, "pos": round(pos, 2)}]), "Ajouter un repère")


def guide_menu(ctl, guide, global_pos):
    """Clic droit sur un repère : le retirer (Ctrl + glisser le déplace)."""
    page, n = guide
    menu = _menu(ctl.pane, "design_guide")

    def drop(i):
        guides = list(i.data.get("guides") or [])
        if 0 <= n < len(guides):
            guides.pop(n)
        i.data["guides"] = guides
    menu.addAction("Retirer ce repère").triggered.connect(lambda: doc.change(ctl.scene, [page], drop, "Repère"))
    menu.popup(global_pos)


def replace_image_dialog(ctl, image):
    from pathlib import Path
    path, _f = QFileDialog.getOpenFileName(ctl.pane, "Remplacer l'image", "",
                                           "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)")
    if path:
        ctl.fill_image(image, Path(path))


def set_page_background_image(ctl, image):
    """L'image devient l'arrière-plan de sa page (couvrante) et disparaît comme élément (une étape)."""
    page = image.page_item()
    if page is None:
        return
    scene = ctl.scene
    scene.commit_live()
    before = scene.snapshot([page.item_id, image.item_id])
    page.data = page.to_dict()
    page.data["bg_asset"] = image.data.get("asset", "")
    page.apply(page.data)
    scene._remove(image.item_id)
    scene.push(before, scene.snapshot([page.item_id, image.item_id]), "Image d'arrière-plan")


def _reset_crop(item):
    """Image entière : taille recalculée à l'échelle actuelle (largeur gardée)."""
    x0, y0, x1, y1 = dm.valid_crop(item.data.get("crop"))
    w, h = item.size()
    full_w, full_h = w / (x1 - x0), h / (y1 - y0)
    item.data.update(crop=[0.0, 0.0, 1.0, 1.0], w=round(full_w, 2), h=round(full_h, 2),
                     x=round(item.data["x"] - x0 * full_w, 2), y=round(item.data["y"] - y0 * full_h, 2))


def shape_kind_menu(ctl, anchor, shapes):
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_shape_kind")
    grid = QWidget()
    layout = QVBoxLayout(grid)
    layout.setContentsMargins(0, 0, 0, 0)
    row = None
    for n, kind in enumerate(k for k in dm.SHAPE_KINDS if k != "line"):
        if n % 6 == 0:
            row = QHBoxLayout()
            row.setSpacing(2)
            layout.addLayout(row)
        button = _GlyphButton(f"design_shape:{kind}", kind, grid, 30)
        button.clicked.connect(lambda _c=False, k=kind: (menu.close(), doc.change(
            ctl.scene, [i for i in shapes if i.data.get("shape") != "line"], lambda i: i.data.update(shape=k),
            "Forme")))
        row.addWidget(button)
    menu_row(menu, "", grid)
    _popup(ctl, menu, anchor)


def mask_menu(ctl, anchor, images):
    """Image dans une forme (cadre de Canva) : la forme découpe l'image, recadrage et réglages inchangés."""
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_mask")
    grid = QWidget()
    row = QHBoxLayout(grid)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(2)
    for kind in dm.MASK_KINDS:
        button = _GlyphButton(f"design_shape:{kind or 'rect'}", kind or "rectangle", grid, 30)
        button.set_on((images[0].data.get("mask") or "") == kind)
        button.clicked.connect(lambda _c=False, k=kind: (menu.close(), doc.change(
            ctl.scene, images, lambda i: i.data.update(mask=k), "Forme du cadre")))
        row.addWidget(button)
    menu_row(menu, "", grid)
    _popup(ctl, menu, anchor)


def text_effects_menu(ctl, anchor, texts):
    """Contour des lettres : épaisseur (0 = aucun) et couleur ; « Creux » = lettres vides cerclées."""
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_text_effects")
    first = texts[0].data
    width = _slider(0, 30, round(float(first.get("text_stroke_width", 0.0))))
    width.valueChanged.connect(lambda v: _live(ctl, "design_text_stroke_width", texts,
                                               lambda i: i.data.update(text_stroke_width=float(v)), "Contour"))
    menu_row(menu, "Contour", width)
    grid = _SwatchGrid(dm.PALETTE, first.get("text_stroke"), 6)

    def pick(color):
        menu.close()

        def change(i):
            i.data["text_stroke"] = color
            if float(i.data.get("text_stroke_width", 0.0)) <= 0:
                i.data["text_stroke_width"] = 2.0
        doc.change(ctl.scene, texts, change, "Contour")
    grid.picked.connect(pick)
    menu_row(menu, "Couleur", grid)
    hollow = menu.addAction("Creux (lettres vides)")
    hollow.triggered.connect(lambda: doc.change(ctl.scene, texts, lambda i: i.data.update(
        text_stroke=i.data.get("color", dm.INK), text_stroke_width=max(2.0, float(i.data.get("text_stroke_width", 0))),
        color="#00000000"), "Creux"))
    menu.addAction("Aucun effet").triggered.connect(lambda: doc.change(
        ctl.scene, texts, lambda i: i.data.update(text_stroke_width=0.0), "Contour"))
    _popup(ctl, menu, anchor)


def font_menu(ctl, anchor, texts):
    from settings_menu import menu_row
    from fm_miro.items import resolve_family
    menu = _menu(ctl.pane, "design_font")
    picker = FontPicker(texts[0].data.get("font_family") or resolve_family(""))

    def chosen(family):
        menu.close()
        doc.change(ctl.scene, texts, lambda i: i.data.update(font_family=family), "Police")
    picker.chosen.connect(chosen)
    menu_row(menu, "", picker)
    menu.aboutToShow.connect(picker.filter.setFocus)
    _popup(ctl, menu, anchor)


def size_menu(ctl, anchor, texts):
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_font_size")
    current = float(texts[0].data.get("font_size", 48))
    slider = _slider(6, 400, round(current), "px")
    slider.valueChanged.connect(lambda v: _live(ctl, "design_font_size", texts,
                                                lambda i: i.data.update(font_size=float(v)), "Taille du texte"))
    menu_row(menu, "Taille", slider)
    for size in (12, 16, 24, 32, 48, 64, 96, 128, 200):
        action = menu.addAction(f"{size}")
        action.setCheckable(True)
        action.setChecked(abs(current - size) < 0.01)
        action.triggered.connect(lambda _c=False, s=size: doc.change(
            ctl.scene, texts, lambda i: i.data.update(font_size=float(s)), "Taille du texte"))
    _popup(ctl, menu, anchor)


def align_menu(ctl, anchor, texts):
    menu = _menu(ctl.pane, "design_align")
    current = texts[0].data.get("align", "left")
    for value, text in (("left", "Gauche (Ctrl+Maj+L)"), ("center", "Centré (Ctrl+Maj+E)"),
                        ("right", "Droite (Ctrl+Maj+R)"), ("justify", "Justifié (Ctrl+Maj+J)")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(current == value)
        action.triggered.connect(lambda _c=False, v=value: doc.change(
            ctl.scene, texts, lambda i: i.data.update(align=v), "Alignement du texte"))
    _popup(ctl, menu, anchor)


def adjust_menu(ctl, anchor, images):
    menu = slider_menu(ctl, anchor, images, [("brightness", "Luminosité", -100, 100, 1.0, ""),
                                             ("contrast", "Contraste", -100, 100, 1.0, ""),
                                             ("saturation", "Saturation", -100, 100, 1.0, ""),
                                             ("blur", "Flou", 0, 100, 1.0, "")], "design_adjust", "Réglages")
    gray = menu.addAction("Noir et blanc")
    gray.setCheckable(True)
    gray.setChecked(bool(images[0].data.get("grayscale")))
    gray.triggered.connect(lambda on: doc.change(ctl.scene, images, lambda i: i.data.update(grayscale=bool(on)),
                                                 "Noir et blanc"))
    filters = menu.addMenu("Filtres")
    for name, values in FILTERS:
        filters.addAction(name).triggered.connect(lambda _c=False, v=values: doc.change(
            ctl.scene, images, lambda i: i.data.update(v), "Filtre"))
    reset = menu.addAction("Réinitialiser les réglages")
    reset.triggered.connect(lambda: doc.change(ctl.scene, images, lambda i: i.data.update(
        brightness=0.0, contrast=0.0, saturation=0.0, blur=0.0, grayscale=False), "Réglages"))
    _popup(ctl, menu, anchor)


# Filtres = jeux de réglages (noms génériques, valeurs choisies ici).
FILTERS = [("Aucun", {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0, "blur": 0.0, "grayscale": False}),
           ("Vif", {"brightness": 5.0, "contrast": 20.0, "saturation": 40.0, "blur": 0.0, "grayscale": False}),
           ("Doux", {"brightness": 10.0, "contrast": -20.0, "saturation": -15.0, "blur": 0.0, "grayscale": False}),
           ("Délavé", {"brightness": 15.0, "contrast": -35.0, "saturation": -40.0, "blur": 0.0, "grayscale": False}),
           ("Noir et blanc contrasté", {"brightness": 0.0, "contrast": 40.0, "saturation": 0.0, "blur": 0.0,
                                        "grayscale": True}),
           ("Sombre", {"brightness": -25.0, "contrast": 15.0, "saturation": -10.0, "blur": 0.0, "grayscale": False}),
           ("Rêveur", {"brightness": 12.0, "contrast": -10.0, "saturation": 10.0, "blur": 6.0, "grayscale": False})]


def flip_menu(ctl, anchor, items):
    menu = _menu(ctl.pane, "design_flip")
    menu.addAction("Retourner horizontalement").triggered.connect(lambda: doc.change(
        ctl.scene, items, lambda i: i.data.update(flip_h=not i.data.get("flip_h")), "Retourner"))
    menu.addAction("Retourner verticalement").triggered.connect(lambda: doc.change(
        ctl.scene, items, lambda i: i.data.update(flip_v=not i.data.get("flip_v")), "Retourner"))
    menu.addAction("Rotation à 0°").triggered.connect(lambda: doc.change(
        ctl.scene, items, lambda i: i.data.update(rotation=0.0), "Rotation"))
    _popup(ctl, menu, anchor)


def resize_menu(ctl, anchor, page):
    """Redimensionner le design : formats, taille personnalisée ; « avec le contenu » = éléments mis à l'échelle."""
    menu = _menu(ctl.pane, "design_resize")
    scale = menu.addAction("Mettre le contenu à l'échelle")
    scale.setCheckable(True)
    scale.setChecked(True)
    menu.addSeparator()
    for key, label, w, h in dm.PAGE_FORMATS:
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(page.data.get("format") == key)
        action.triggered.connect(lambda _c=False, k=key, w=w, h=h: doc.resize_page(
            ctl.scene, page, w, h, scale.isChecked(), k))
    custom = menu.addAction("Taille personnalisée…")
    custom.triggered.connect(lambda: QTimer.singleShot(0, lambda: custom_size(ctl, page, scale.isChecked())))
    _popup(ctl, menu, anchor)


def ask_size(parent, w0=1080, h0=1080):
    text, ok = QInputDialog.getText(parent, "Taille personnalisée", "Largeur × hauteur (px, ou « 210x297 mm ») :",
                                    text=f"{round(w0)} x {round(h0)}")
    if not ok:
        return None
    return parse_size(text)


def parse_size(text: str):
    """« 1200 x 628 », « 1200×628 px », « 210 x 297 mm », « 8.5 x 11 in » -> (largeur, hauteur) en unités du board."""
    import re
    match = re.match(r"\s*([\d.,]+)\s*[x×*]\s*([\d.,]+)\s*(px|mm|cm|in)?\s*$", text or "", re.I)
    if not match:
        return None
    try:
        w, h = (float(v.replace(",", ".")) for v in match.group(1, 2))
    except ValueError:
        return None
    unit = (match.group(3) or "px").lower()
    k = {"px": 1.0, "mm": dm.MM, "cm": dm.MM * 10, "in": 96.0}[unit]
    w, h = round(w * k, 2), round(h * k, 2)
    if not (1 <= w <= 20000 and 1 <= h <= 20000):
        return None
    return w, h


def custom_size(ctl, page, scale):
    size = ask_size(ctl.pane, *page.size())
    if size:
        doc.resize_page(ctl.scene, page, size[0], size[1], scale, "custom")


def export_menu(ctl, anchor):
    """Exporter : format, pages, échelle, qualité JPEG, fond transparent (PNG), puis le fichier."""
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_export")
    state = ctl.__dict__.setdefault("_export", {"fmt": "png", "scope": "all", "scale": 100, "quality": 92,
                                                "transparent": False, "bleed": False, "marks": False})
    for fmt, text in (("png", "PNG (image)"), ("jpg", "JPEG (image, plus léger)"), ("pdf", "PDF (multipage)"),
                      ("svg", "SVG (vectoriel)")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(state["fmt"] == fmt)
        action.triggered.connect(lambda _c=False, f=fmt: (state.update(fmt=f), QTimer.singleShot(
            0, lambda: export_menu(ctl, anchor))))
    menu.addSeparator()
    for scope, text in (("all", "Toutes les pages"), ("current", "Page courante"), ("range", "Pages choisies…")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(state["scope"] == scope)
        action.triggered.connect(lambda _c=False, s=scope: (state.update(scope=s), QTimer.singleShot(
            0, lambda: export_menu(ctl, anchor))))
    if state["fmt"] in ("png", "jpg"):
        scale = _slider(25, 400, state["scale"], "%")
        scale.valueChanged.connect(lambda v: state.update(scale=v))
        menu_row(menu, "Taille", scale)
    if state["fmt"] == "jpg":
        quality = _slider(10, 100, state["quality"], "%")
        quality.valueChanged.connect(lambda v: state.update(quality=v))
        menu_row(menu, "Qualité", quality)
    if state["fmt"] == "pdf":
        for key, text in (("bleed", "Fond perdu (3 mm, impression)"), ("marks", "Traits de coupe")):
            action = menu.addAction(text)
            action.setCheckable(True)
            action.setChecked(bool(state.get(key)))
            action.triggered.connect(lambda on, k=key: state.update({k: bool(on)}))
    if state["fmt"] == "png":
        transparent = menu.addAction("Fond transparent")
        transparent.setCheckable(True)
        transparent.setChecked(state["transparent"])
        transparent.triggered.connect(lambda on: state.update(transparent=bool(on)))
    menu.addSeparator()
    go = menu.addAction("Exporter…")
    go.triggered.connect(lambda: QTimer.singleShot(0, lambda: run_export(ctl, state)))
    _popup(ctl, menu, anchor)


def run_export(ctl, state):
    from pathlib import Path
    from . import render
    from . import geometry
    pages = ctl.pages()
    if state["scope"] == "current":
        current = ctl.current_page()
        pages = [current] if current is not None else []
    elif state["scope"] == "range":
        text, ok = QInputDialog.getText(ctl.pane, "Exporter", f"Pages (ex. « 1-3, 5 » ; {len(pages)} pages) :",
                                        text=state.get("range", "1"))
        if not ok:
            return
        state["range"] = text
        pages = [pages[n] for n in geometry.parse_pages(text, len(pages))]
    if not pages:
        return
    base = ctl.scene.board_path
    start = str(Path(base).with_suffix(f".{state['fmt']}")) if base else f"design.{state['fmt']}"
    filters = {"png": "Image PNG (*.png)", "jpg": "Image JPEG (*.jpg *.jpeg)", "pdf": "PDF (*.pdf)",
               "svg": "SVG (*.svg)"}
    path, _f = QFileDialog.getSaveFileName(ctl.pane, "Exporter le design", start, filters[state["fmt"]])
    if not path:
        return
    try:
        written = render.export_pages(pages, path, state["fmt"], state["scale"] / 100.0, state["quality"],
                                      state["transparent"], 3.0 if state.get("bleed") else 0.0,
                                      bool(state.get("marks")))
    except (OSError, ValueError) as error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(ctl.pane, "Exporter", f"Export impossible : {error}")
        return
    ctl.pane._state.setText(f"Exporté : {len(written)} fichier(s)")
