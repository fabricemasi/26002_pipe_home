"""Interface du module Design (à la manière de Canva, avec les briques du board et des réglages) :
- RAIL à gauche (modèles, éléments, texte, images, position et calques, export) qui ouvre le PANNEAU latéral
  (`panels.py`) ;
- barre CONTEXTUELLE en haut : commandes de la sélection (forme, texte, image, communes) ou de la page ;
- barre des PAGES en bas : miniatures (clic = aller à la page, Ctrl + glisser = réordonner, clic droit = menu), « + ».
Barres = `fm_board.ui._bar` (habillage Réglages > Module MRO > Barres d'outils), menus = `settings_menu.Menu`,
curseurs / couleurs / polices = champs des réglages. Contenu refait seulement quand la sélection change (une fois par
passage de boucle) ; miniatures refaites 300 ms après un changement, seulement celles des pages modifiées."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QHBoxLayout, QInputDialog, QScrollArea,
                               QVBoxLayout, QWidget)

from fm_board.ui import FontPicker, _bar, _GlyphButton, _menu, _panel, _slider, _SwatchGrid, _TextButton
from . import design_model as dm, document as doc
from .items import DesignImageItem, DesignShapeItem, DesignTextItem

TABS = [("templates", "design_templates", "Modèles et formats"), ("elements", "design_elements", "Éléments"),
        ("text", "design_text", "Texte"), ("images", "design_images", "Images"),
        ("layers", "design_layers", "Position et calques")]
PANEL_W = 300
THUMB_H = 54


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
        order = menu.addMenu("Ordre")
        for how, text in (("front", "Premier plan"), ("forward", "Avancer"), ("backward", "Reculer"),
                          ("back", "Arrière-plan")):
            order.addAction(text).triggered.connect(lambda _c=False, h=how: doc.restack(ctl.scene, items, h))
        images = [i for i in items if isinstance(i, DesignImageItem)]
        if len(images) == 1:
            menu.addAction("Recadrer").triggered.connect(lambda: ctl.start_crop(images[0]))
            menu.addAction("Définir comme arrière-plan de la page").triggered.connect(
                lambda: set_page_background_image(ctl, images[0]))
    page = ctl.current_page()
    if page is not None:
        menu.addSeparator()
        menu.addAction("Couleur de la page…").triggered.connect(
            lambda: QTimer.singleShot(0, lambda: fill_menu(ctl, ctl.ui.context, [page],
                                                           ("background", "bg_type", "bg2", "bg_angle"), "Fond de page")))
        if page.data.get("bg_asset"):
            menu.addAction("Retirer l'image d'arrière-plan").triggered.connect(
                lambda: doc.change(ctl.scene, [page], lambda i: i.data.update(bg_asset=""), "Arrière-plan"))
    menu.aboutToHide.connect(ctl.scene.commit_live)
    menu.popup(global_pos)


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


# ---------------------------------------------------------------- miniatures des pages
class PageThumb(QAbstractButton):
    """Miniature d'une page : clic = y aller ; Ctrl + glisser = réordonner (règle de l'appli) ; clic droit = menu."""

    def __init__(self, chrome, page, parent):
        super().__init__(parent)
        self.chrome = chrome
        self.page_id = page.item_id
        self.pixmap = None
        self.number = 1
        self.current = False
        self._press = None
        w, h = page.size()
        self.setFixedSize(QSize(max(30, min(110, round(THUMB_H * w / max(1.0, h)))) + 6, THUMB_H + 18))
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("Clic : aller à la page · Ctrl + glisser : réordonner · clic droit : menu")

    def paintEvent(self, _event):
        from app_style import C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(3, 3, self.width() - 6, THUMB_H)
        if self.pixmap is not None:
            p.drawPixmap(box, self.pixmap, QRectF(self.pixmap.rect()))
        else:
            p.fillRect(box, QColor("#ffffff"))
        p.setPen(QPen(QColor(dm.ACCENT) if self.current else QColor(255, 255, 255, 50), 2.0 if self.current else 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(0, THUMB_H + 3, self.width(), 15), Qt.AlignCenter, str(self.number))
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = (event.position(), bool(QApplication.keyboardModifiers() & Qt.ControlModifier))
        elif event.button() == Qt.RightButton:
            self.chrome.page_menu(self.page_id, event.globalPosition().toPoint())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is not None and self._press[1] and (event.position() - self._press[0]).manhattanLength() > 4:
            self.chrome.drag_page(self, event)
        event.accept()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if press is None:
            return
        if self.chrome.dragging is self:
            self.chrome.drop_page(self)
        elif (event.position() - press[0]).manhattanLength() <= 4:
            self.chrome.go_to_page(self.page_id)
        event.accept()


# ---------------------------------------------------------------- chrome
class DesignChrome(QObject):
    def __init__(self, pane, ctl):
        super().__init__(pane)
        from settings_theme import _text_label
        self.pane = pane
        self.ctl = ctl
        self.scene = ctl.scene
        self.tab = None
        self.dragging = None
        self._dirty_pages: set | None = None        # pages dont la miniature est à refaire (None = toutes)
        self.rail, rail = _bar(pane, True)
        rail.setAlignment(Qt.AlignHCenter)
        self._rail_buttons = {}
        for name, glyph, tip in TABS:
            button = _GlyphButton(glyph, tip, self.rail)
            button.clicked.connect(lambda _c=False, n=name: self.set_tab(None if self.tab == n else n))
            rail.addWidget(button)
            self._rail_buttons[name] = button
        rail.addSpacing(10)
        export = _GlyphButton("design_export", "Exporter (PNG, JPEG, PDF, SVG)", self.rail)
        export.clicked.connect(lambda: export_menu(ctl, export))
        rail.addWidget(export)
        present = _GlyphButton("design_present", "Présenter en plein écran (Ctrl+Alt+P)", self.rail)
        present.clicked.connect(lambda: ctl.present())
        rail.addWidget(present)
        self.panel, panel = _panel(pane, True)
        self.panel.setFixedWidth(PANEL_W)
        panel.setContentsMargins(10, 10, 10, 10)
        panel.setSpacing(8)
        self.panel_title = _text_label("", "card_title")
        panel.addWidget(self.panel_title)
        self.scroll = QScrollArea(self.panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Contenu OPAQUE (fond du panneau) : Qt ne repeint plus le panneau à chaque image du board dessous (il retire
        # les voisins opaques de la zone à peindre) — les miniatures des modèles étaient repeintes à chaque image.
        from settings_store import M
        self.scroll.setStyleSheet(f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: {M['panel_bg']}; }}")
        self.scroll.viewport().setAutoFillBackground(True)
        panel.addWidget(self.scroll, 1)
        self.panel_content = None
        self.context, self.context_layout = _bar(pane, False)
        self.pagebar, pages = _bar(pane, False)
        self.pages_layout = QHBoxLayout()
        self.pages_layout.setSpacing(4)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        pages.addLayout(self.pages_layout)
        add = _GlyphButton("design_add_page", "Ajouter une page (même format que la page courante)", self.pagebar)
        add.clicked.connect(self.add_page)
        pages.addWidget(add)
        self._thumbs: list[PageThumb] = []
        for widget in (self.rail, self.panel, self.context, self.pagebar):
            widget.hide()
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.sync)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(300)
        self._thumb_timer.timeout.connect(self.refresh_thumbs)
        ctl.stateChanged.connect(self.schedule_sync)
        ctl.pagesChanged.connect(self.rebuild_pages)
        self.scene.contentChanged.connect(self._content_changed)
        self.scene.undo.indexChanged.connect(self._mark_from_undo)

    # -- visibilité, place --
    def show(self):
        for widget in (self.rail, self.context, self.pagebar):
            widget.show()
        self.panel.setVisible(self.tab is not None)
        if self.tab is None and not self.ctl.pages():
            self.set_tab("templates")                    # aucun design : choisir un format d'abord
        self.rebuild_pages()
        self.sync()

    def hide(self):
        for widget in (self.rail, self.panel, self.context, self.pagebar):
            widget.hide()

    def place(self):
        pane = self.pane
        if not self.ctl.active:
            return
        margin = 16
        title = pane.title_area()
        for widget in (self.rail, self.context, self.pagebar):
            widget.layout().activate()
            widget.resize(widget.sizeHint())
        top = title.bottom() + 10
        self.rail.move(margin, max(top, (pane.height() - self.rail.height()) // 2))
        self.panel.move(self.rail.geometry().right() + 8, top)
        self.panel.resize(PANEL_W, max(200, pane.height() - top - margin))
        left = title.right() + 12
        room = pane.width() - left - margin
        if self.context.width() <= room:
            self.context.move(left + max(0, (room - self.context.width()) // 2), margin)
        else:
            self.context.move(max(margin, (pane.width() - self.context.width()) // 2), top)
        zoom_w = pane._zoombar.width() + 24
        width = min(self.pagebar.sizeHint().width(), pane.width() - 2 * (zoom_w + margin))
        self.pagebar.resize(max(80, width), self.pagebar.sizeHint().height())
        self.pagebar.move(max(margin, (pane.width() - self.pagebar.width()) // 2),
                          pane.height() - self.pagebar.height() - margin)
        for widget in (self.rail, self.panel, self.context, self.pagebar):
            widget.raise_()

    def free_area(self) -> QRect:
        """Partie du board (coordonnées du viewport) que ne couvrent ni le panneau, ni les barres du haut et du bas."""
        view = self.pane.view
        rect = view.viewport().rect()
        left = (self.panel if self.panel.isVisible() else self.rail).geometry().right() + 12
        top = max(self.context.geometry().bottom() if self.context.isVisible() else 0,
                  self.pane.title_area().bottom()) + 30
        bottom = (self.pagebar.geometry().top() if self.pagebar.isVisible() else rect.bottom()) - 10
        origin = view.viewport().mapFrom(self.pane, QPoint(0, 0))
        free = QRect(left + origin.x(), top + origin.y(), rect.width() - left - 12, bottom - top)
        return free if free.width() > 200 and free.height() > 200 else rect

    # -- panneau latéral --
    def set_tab(self, name):
        self.tab = name
        for key, button in self._rail_buttons.items():
            button.set_on(key == name)
        if name is None:
            self.panel.hide()
            self.pane.view.setFocus()
            return
        from . import panels
        self.panel_title.setText(dict((n, t) for n, _g, t in TABS)[name])
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.panel_content = panels.build(name, self.ctl, self.scroll)
        self.scroll.setWidget(self.panel_content)
        self.panel.show()
        self.place()

    def refresh_panel(self):
        """Panneau dépendant de la sélection (position et calques) : refait."""
        if self.tab == "layers" and self.panel.isVisible():
            if self.panel_content is not None and hasattr(self.panel_content, "sync"):
                self.panel_content.sync()
            else:
                self.set_tab("layers")

    # -- barre contextuelle --
    def schedule_sync(self):
        if self.ctl.active:
            self._sync_timer.start()

    def _mark_from_undo(self, index):
        """Pages touchées par la commande faite / défaite (et ses sous-commandes d'une macro)."""
        try:
            stack = self.scene.undo
            for n in (index - 1, index):
                if 0 <= n < stack.count():
                    self._mark_command(stack.command(n))
        except RuntimeError:                         # board fermé : la pile part avant ce signal
            pass

    def _mark_command(self, command):
        if command is None:
            return
        for states in (getattr(command, "before", None), getattr(command, "after", None)):
            for item_id, state in (states or {}).items():
                self._mark_state(item_id, state)
        for n in range(command.childCount()):
            self._mark_command(command.child(n))

    def _mark_state(self, item_id, state):
        if self._dirty_pages is None:
            return
        if isinstance(state, dict) and state.get("type") == dm.PAGE:
            self._dirty_pages.add(item_id)
        elif isinstance(state, dict) and state.get("page"):
            self._dirty_pages.add(state["page"])

    def _content_changed(self):
        if not self.ctl.active:
            return
        if self._dirty_pages is not None:                  # changement en direct (curseur) : pages de la sélection
            for item in self.ctl.selection():
                self._dirty_pages.add(item.data.get("page", ""))
            page = self.ctl.current_page()
            if page is not None and not self.ctl.selection():
                self._dirty_pages.add(page.item_id)
        self._thumb_timer.start()
        if QApplication.activePopupWidget() is None:
            self.schedule_sync()

    def sync(self):
        if not self.ctl.active:
            return
        self._clear(self.context_layout)
        build_context_bar(self, self.ctl)
        for n in range(self.context_layout.count()):        # barre déjà visible : ses nouveaux boutons aussi
            widget = self.context_layout.itemAt(n).widget()
            if widget is not None:
                widget.show()
        self.context.setVisible(self.context_layout.count() > 0)
        self.refresh_panel()
        self._sync_thumbs_current()
        self.place()

    @staticmethod
    def _clear(layout):
        while layout.count():
            entry = layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
            elif entry.layout() is not None:
                DesignChrome._clear(entry.layout())

    # -- pages --
    def rebuild_pages(self):
        self._clear(self.pages_layout)
        self._thumbs = []
        self._dirty_pages = None
        for page in self.ctl.pages():
            thumb = PageThumb(self, page, self.pagebar)
            self.pages_layout.addWidget(thumb)
            thumb.setVisible(self.pagebar.isVisible())
            self._thumbs.append(thumb)
        self.refresh_thumbs()
        self.place()

    def _sync_thumbs_current(self):
        current = self.ctl.current_page()
        pages = self.ctl.pages()
        if [t.page_id for t in self._thumbs] != [p.item_id for p in pages]:
            self.rebuild_pages()
            return
        for n, thumb in enumerate(self._thumbs, 1):
            on = current is not None and thumb.page_id == current.item_id
            if thumb.current != on or thumb.number != n:
                thumb.current, thumb.number = on, n
                thumb.update()

    def refresh_thumbs(self):
        """Miniatures des pages MODIFIÉES seulement (pages touchées par les commandes d'annulation et les changements
        en direct depuis la dernière fois ; toutes après une reconstruction de la barre)."""
        from . import render
        pages = {p.item_id: p for p in self.ctl.pages()}
        if [t.page_id for t in self._thumbs] != list(pages):
            self.rebuild_pages()
            return
        ratio = self.pagebar.devicePixelRatioF() or 1.0
        for thumb in self._thumbs:
            page = pages.get(thumb.page_id)
            if page is None:
                continue
            if self._dirty_pages is None or thumb.page_id in self._dirty_pages:
                thumb.pixmap = render.thumbnail(page, thumb.width() - 6, THUMB_H, ratio)
                thumb.update()
        self._dirty_pages = set()
        self._sync_thumbs_current()

    def go_to_page(self, page_id):
        page = self.scene.item(page_id)
        if page is not None:
            self.ctl.set_current_page(page, show=True)

    def add_page(self):
        current = self.ctl.current_page()
        if current is None:
            self.ctl.ensure_page()
            return
        w, h = current.size()
        page = doc.add_page(self.scene, w, h, after=current, values={"format": current.data.get("format", "custom")})
        self.ctl.set_current_page(page, show=True)
        self.rebuild_pages()

    def page_menu(self, page_id, global_pos):
        page = self.scene.item(page_id)
        if page is None:
            return
        pages = self.ctl.pages()
        menu = _menu(self.pane, "design_page")
        menu.addAction("Dupliquer la page").triggered.connect(lambda: self._after(doc.duplicate_page(self.scene, page)))
        menu.addAction("Renommer…").triggered.connect(lambda: QTimer.singleShot(0, lambda: self.rename_page(page)))
        index = pages.index(page)
        if index > 0:
            menu.addAction("Monter").triggered.connect(lambda: self._move(page, index - 1))
        if index < len(pages) - 1:
            menu.addAction("Descendre").triggered.connect(lambda: self._move(page, index + 1))
        menu.addAction("Redimensionner…").triggered.connect(
            lambda: QTimer.singleShot(0, lambda: resize_menu(self.ctl, self.pagebar, page)))
        menu.addSeparator()
        if len(pages) > 1:
            menu.addAction("Supprimer la page").triggered.connect(lambda: self._delete(page))
        else:
            menu.addAction("Supprimer le design (page et éléments)").triggered.connect(lambda: self._delete(page))
        menu.popup(global_pos)

    def _after(self, page):
        self.ctl.set_current_page(page, show=True)
        self.rebuild_pages()

    def _move(self, page, index):
        doc.move_page(self.scene, page, index)
        self.rebuild_pages()

    def _delete(self, page):
        doc.delete_page(self.scene, page)
        self.rebuild_pages()
        self.ctl.stateChanged.emit()

    def rename_page(self, page):
        name, ok = QInputDialog.getText(self.pane, "Renommer la page", "Nom :", text=page.data.get("name", ""))
        if ok:
            doc.change(self.scene, [page], lambda i: i.data.update(name=name.strip()), "Renommer la page")

    def drag_page(self, thumb, event):
        """Ctrl + glisser une miniature : fantôme (opacité DRAG_GHOST_OPACITY), place d'arrivée marquée."""
        from settings_widgets import DRAG_GHOST_OPACITY
        if self.dragging is None:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            self.dragging = thumb
            effect = QGraphicsOpacityEffect(thumb)
            effect.setOpacity(DRAG_GHOST_OPACITY)
            thumb.setGraphicsEffect(effect)
            thumb.raise_()
        x = thumb.mapTo(self.pagebar, event.position().toPoint()).x()
        thumb.move(x - thumb.width() // 2, thumb.y())

    def drop_page(self, thumb):
        self.dragging = None
        center = thumb.geometry().center().x()
        others = [t for t in self._thumbs if t is not thumb]
        index = sum(1 for t in others if t.geometry().center().x() < center)
        page = self.scene.item(thumb.page_id)
        if page is not None:
            doc.move_page(self.scene, page, index)
        self.rebuild_pages()


# ---------------------------------------------------------------- barre contextuelle
def build_context_bar(chrome, ctl):
    bar = chrome.context
    add = chrome.context_layout.addWidget
    sel = ctl.selection()

    def glyph(kind, tip, slot, on=False):
        button = _GlyphButton(kind, tip, bar, 32)
        button.set_on(on)
        button.clicked.connect(lambda _c=False, b=button: slot(b))
        add(button)
        return button

    def text_button(text, tip, slot, width=0):
        button = _TextButton(text, tip, bar, width)
        button.clicked.connect(lambda _c=False, b=button: slot(b))
        add(button)
        return button

    def swatch(color, tip, slot):
        button = _GlyphButton("swatch", tip, bar, 32)
        button.set_swatch(color or "#ffffff")
        button.clicked.connect(lambda _c=False, b=button: slot(b))
        add(button)

    if ctl.crop_item is not None:
        text_button("Terminer le recadrage", "Entrée", lambda _b: ctl.end_crop())
        item = ctl.crop_item
        text_button("Rétablir", "Image entière", lambda _b: doc.change(
            ctl.scene, [item], lambda i: _reset_crop(i), "Recadrer"))
        return
    page = ctl.current_page()
    if not sel:
        if page is None:
            text_button("Créer un design…", "Choisir un format", lambda _b: chrome.set_tab("templates"))
            return
        swatch(page.data.get("background"), "Couleur de la page", lambda b: fill_menu(
            ctl, b, [page], ("background", "bg_type", "bg2", "bg_angle"), "Fond de page"))
        glyph("design_resize", "Redimensionner le design", lambda b: resize_menu(ctl, b, page))
        w, h = page.size()
        text_button(f"{round(w)} × {round(h)} px", "Dimensions de la page", lambda b: resize_menu(ctl, b, page))
        return
    shapes = [i for i in sel if isinstance(i, DesignShapeItem)]
    texts = [i for i in sel if isinstance(i, DesignTextItem)]
    images = [i for i in sel if isinstance(i, DesignImageItem)]
    locked = all(i.locked() for i in sel)
    if not locked:
        if shapes:
            first = shapes[0]
            glyph(f"shape:{first.data.get('shape', 'rect') if first.data.get('shape') != 'line' else 'rect'}",
                  "Forme", lambda b: shape_kind_menu(ctl, b, shapes))
            if any(i.data.get("shape") != "line" for i in shapes):
                closed = [i for i in shapes if i.data.get("shape") != "line"]
                swatch(closed[0].data.get("fill") if closed[0].data.get("fill_type") != "none" else "#00000000",
                       "Couleur de remplissage, dégradé", lambda b: fill_menu(ctl, b, closed))
        if texts:
            first = texts[0]
            from fm_miro.items import resolve_family
            family = first.data.get("font_family") or resolve_family("")
            text_button(family[:16], "Police", lambda b: font_menu(ctl, b, texts), 130)
            text_button(f"{first.data.get('font_size', 48):g}", "Taille (Ctrl+Maj+> / <)",
                        lambda b: size_menu(ctl, b, texts), 54)
            swatch(first.data.get("color"), "Couleur du texte", lambda b: color_menu(ctl, b, texts, "color",
                                                                                     "Couleur du texte"))
            for field, kind, tip in (("bold", "design_bold", "Gras (Ctrl+B)"),
                                     ("italic", "design_italic", "Italique (Ctrl+I)"),
                                     ("underline", "design_underline", "Souligné (Ctrl+U)"),
                                     ("uppercase", "design_upper", "Majuscules (Ctrl+Maj+K)")):
                on = all(i.data.get(field) for i in texts)
                glyph(kind, tip, lambda _b, f=field, o=on: doc.change(ctl.scene, texts,
                                                                       lambda i: i.data.update({f: not o}), tip),
                      on)
            glyph("align", "Alignement du texte", lambda b: align_menu(ctl, b, texts))
            glyph("design_spacing", "Espacement des lettres, interligne", lambda b: _popup(ctl, slider_menu(
                ctl, b, texts, [("letter_spacing", "Lettres", -200, 800, 1.0, ""),
                                ("line_height", "Interligne", 50, 300, 100.0, "%")], "design_spacing",
                "Espacement"), b))
            glyph("highlight", "Surlignage du texte", lambda b: color_menu(ctl, b, texts, "text_bg", "Surlignage",
                                                                         allow_none=True))
        if images:
            glyph("design_crop", "Recadrer (double-clic)", lambda _b: ctl.start_crop(images[0]))
            glyph("design_adjust", "Réglages de l'image", lambda b: adjust_menu(ctl, b, images))
        stroked = shapes + images
        if stroked:
            glyph("border", "Contour, arrondi, extrémités", lambda b: stroke_menu(ctl, b, stroked))
        glyph("design_opacity", "Transparence", lambda b: _popup(ctl, slider_menu(
            ctl, b, sel, [("opacity", "Opacité", 0, 100, 100.0, "%")], "design_opacity", "Transparence"), b))
        glyph("design_shadow", "Ombre portée", lambda b: shadow_menu(ctl, b, sel))
        glyph("design_flip", "Retourner", lambda b: flip_menu(ctl, b, sel))
        glyph("design_position", "Position : ordre, alignement, répartition", lambda b: position_menu(ctl, b, sel))
        grouped = len(sel) > 1 and len({i.data.get("group") for i in sel}) == 1 and bool(sel[0].data.get("group"))
        if len(sel) > 1:
            glyph("design_ungroup" if grouped else "design_group",
                  "Dissocier (Ctrl+Maj+G)" if grouped else "Grouper (Ctrl+G)",
                  lambda _b: (doc.set_group(ctl.scene, sel, not grouped), ctl.stateChanged.emit()))
        glyph("design_duplicate", "Dupliquer (Ctrl+D)", lambda _b: ctl.duplicate())
    glyph("lock", "Déverrouiller" if locked else "Verrouiller (Alt+Maj+L)", lambda _b: ctl.toggle_lock(), locked)
    if not locked:
        glyph("design_delete", "Supprimer (Suppr)", lambda _b: ctl.scene.delete_items(sel))


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
        button = _GlyphButton(f"shape:{kind}", kind, grid, 30)
        button.clicked.connect(lambda _c=False, k=kind: (menu.close(), doc.change(
            ctl.scene, [i for i in shapes if i.data.get("shape") != "line"], lambda i: i.data.update(shape=k),
            "Forme")))
        row.addWidget(button)
    menu_row(menu, "", grid)
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
                                                "transparent": False})
    for fmt, text in (("png", "PNG (image)"), ("jpg", "JPEG (image, plus léger)"), ("pdf", "PDF (multipage)"),
                      ("svg", "SVG (vectoriel)")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(state["fmt"] == fmt)
        action.triggered.connect(lambda _c=False, f=fmt: (state.update(fmt=f), QTimer.singleShot(
            0, lambda: export_menu(ctl, anchor))))
    menu.addSeparator()
    for scope, text in (("all", "Toutes les pages"), ("current", "Page courante")):
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
    pages = ctl.pages()
    if state["scope"] == "current":
        current = ctl.current_page()
        pages = [current] if current is not None else []
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
                                      state["transparent"])
    except (OSError, ValueError) as error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(ctl.pane, "Exporter", f"Export impossible : {error}")
        return
    ctl.pane._state.setText(f"Exporté : {len(written)} fichier(s)")

