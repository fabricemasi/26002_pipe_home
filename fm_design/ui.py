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
from PySide6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QInputDialog, QScrollArea

from fm_board.ui import _bar, _GlyphButton, _menu, _panel, _TextButton
from . import design_model as dm, document as doc
from .menus import (_popup, _reset_crop, adjust_menu, align_menu, color_menu, export_menu, fill_menu,
                    flip_menu, font_menu, mask_menu, position_menu, resize_menu, shadow_menu, shape_kind_menu,
                    size_menu, slider_menu, stroke_menu, text_effects_menu)
from .items import DesignImageItem, DesignShapeItem, DesignTextItem

TABS = [("templates", "design_templates", "Modèles et formats"), ("elements", "design_elements", "Éléments"),
        ("text", "design_text", "Texte"), ("images", "design_images", "Images"),
        ("layers", "design_layers", "Position et calques")]
PANEL_W = 300
THUMB_H = 54


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
            glyph(f"design_shape:{first.data.get('shape', 'rect')}", "Forme", lambda b: shape_kind_menu(ctl, b, shapes))
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
            glyph("design_effects", "Effets : contour des lettres", lambda b: text_effects_menu(ctl, b, texts))
        if images:
            glyph("design_crop", "Recadrer (double-clic)", lambda _b: ctl.start_crop(images[0]))
            glyph(f"design_shape:{images[0].data.get('mask') or 'rect'}", "Forme du cadre (masque)",
                  lambda b: mask_menu(ctl, b, images))
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
