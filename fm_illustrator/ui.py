"""Interface du module Illustrator (briques du board et des réglages, aucun style inventé) : BARRES FLOTTANTES du système
de fm_theme (`fm_board.bars.BoardBars`, disposition dans `bars.py`, enregistrée sous `board_bars["illustrator"]`) :
- barres d'OUTILS (« Sélection », « Tracé », « Créer », « Transformer ») clipsées à gauche, puis « Couleur » : le témoin
  fond / contour (`bars.FillStrokeTool`) et l'échange ;
- barre « Propriétés » en haut : titre de la sélection, fond, contour, épaisseur, opacité de la sélection (ou du style
  courant) ; barre « Objet » : disposition, pinceaux, aligner, Pathfinder, effets, plans de travail, calques, export ;
- barre « Texte » (police, corps, paragraphe) : visible seulement quand la sélection contient un texte.
Contenu mis à jour seulement quand la sélection ou l'outil change (`stateChanged`, regroupé par passage de boucle) ;
les textes des boutons changent par `set_text` (rien n'est refait). Le panneau Calques reste un panneau (liste)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QRect, QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from fm_board.bars import BoardBars, BoardTool
from fm_board.ui import _GlyphButton, _menu, _panel, _slider, _SwatchGrid
from fm_theme.palette import PaletteSliderBar, PaletteTextButton
from . import look, model, paint
from .bars import FillStrokeTool, StatusText, default_state

TOOL_GROUPS = [
    [("select", "ill_select"), ("direct", "ill_direct")],
    [("pen", "ill_pen"), ("add_anchor", "ill_add_anchor"), ("delete_anchor", "ill_delete_anchor"),
     ("convert", "ill_convert")],
    [("type", "ill_text"), ("paintbrush", "ill_brush"), ("blob", "ill_blob"), ("width", "ill_width")],
    [("rect", "ill_rect"), ("ellipse", "ill_ellipse"), ("polygon", "ill_polygon"), ("star", "ill_star"),
     ("line", "ill_line"), ("pencil", "ill_pencil")],
    [("rotate", "ill_rotate"), ("scale", "ill_scale"), ("reflect", "ill_reflect")],
    [("shape_builder", "ill_shape_builder"), ("gradient", "ill_gradient"), ("eyedropper", "ill_eyedropper")],
    [("artboard", "ill_artboard"), ("hand", "ill_hand"), ("zoom", "ill_zoom")],
]
STROKE_WIDTHS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0]


class IllustratorChrome(QObject):
    def __init__(self, pane, ctl):
        super().__init__(pane)
        self.pane = pane
        self.ctl = ctl
        # Barres FLOTTANTES (fm_theme/bar_manager.py, fm_board/bars.py) : leur aspect est celui de fm_theme (section
        # « Palette » de l'éditeur), la disposition est retenue par l'utilisateur (`board_bars["illustrator"]`).
        self._no_bar = QWidget(pane)               # (à la place d'une barre supprimée : `tools` et `control` restent utilisables)
        self._no_bar.hide()
        self.bars = BoardBars(pane, "illustrator", default_state())
        register = self.bars.register
        self._tool_buttons = {}
        for group in TOOL_GROUPS:
            for name, glyph in group:
                button = BoardTool(glyph, ctl.tools[name].label, key=name)
                button.clicked.connect(lambda _c=False, n=name: ctl.set_tool(n))
                register(name, button)
                self._tool_buttons[name] = button
        self.fill_stroke = FillStrokeTool(ctl, self.current_values, self.pick_color)
        register("fill_stroke", self.fill_stroke)
        self.swap_button = BoardTool("ill_swap", "Intervertir fond et contour (Maj+X)", key="swap")
        self.swap_button.clicked.connect(ctl.swap_fill_stroke)
        register("swap", self.swap_button)

        self.title = StatusText("title", "Aucune sélection", "Sélection", cells=3)
        register("title", self.title)
        self.fill_button = BoardTool("fill", "Fond", key="fill")
        self.fill_button.clicked.connect(lambda: self.pick_color("fill", self.fill_button))
        register("fill", self.fill_button)
        self.stroke_button = BoardTool("border", "Contour", key="stroke")
        self.stroke_button.clicked.connect(lambda: self.pick_color("stroke", self.stroke_button))
        register("stroke", self.stroke_button)
        self.width_button = PaletteTextButton("stroke_width", "1 pt", "Épaisseur du contour", cells=2)
        self.width_button.clicked.connect(self.width_menu)
        register("stroke_width", self.width_button)
        self.opacity = PaletteSliderBar("opacity", "Opacité", 0, 100, 100, "%")
        self.opacity.setToolTip("Opacité")
        self.opacity.valueChanged.connect(lambda v: ctl.live_style("opacity", v / 100.0, "Opacité"))
        register("opacity", self.opacity)

        self.object_button = PaletteTextButton("object", "Objet", "Disposition, groupe, symétries, tracés", cells=2)
        self.object_button.clicked.connect(lambda: self.object_menu(self.object_button))
        register("object", self.object_button)
        self.brush_button = BoardTool("ill_brush", "Pinceau : profil de largeur, pointe calligraphique, "
                                      "forme de tache", key="brush")
        self.brush_button.clicked.connect(lambda: self.brush_menu(self.brush_button))
        register("brush", self.brush_button)
        self.align_button = BoardTool("ill_align", "Aligner et répartir", key="align")
        self.align_button.clicked.connect(lambda: self.align_menu(self.align_button))
        register("align", self.align_button)
        self.pathfinder_button = BoardTool("ill_pathfinder", "Pathfinder (modes de forme, division…)", key="pathfinder")
        self.pathfinder_button.clicked.connect(lambda: self.pathfinder_menu(self.pathfinder_button))
        register("pathfinder", self.pathfinder_button)
        self.effects_button = BoardTool("ill_fx", "Effets et aspect (ombre, lueur, flou, décalage, arrondis, "
                                        "contours supplémentaires)", key="effects")
        self.effects_button.clicked.connect(lambda: self._effects(self.effects_button))
        register("effects", self.effects_button)
        self.board_button = PaletteTextButton("artboards", "Plans de travail", "Nouveau plan de travail, formats", cells=3)
        self.board_button.clicked.connect(lambda: self.artboard_menu(self.board_button))
        register("artboards", self.board_button)
        self.layers_button = BoardTool("ill_layers", "Calques", key="layers")
        self.layers_button.clicked.connect(self.toggle_layers)
        register("layers", self.layers_button)
        self.export_button = BoardTool("ill_export", "Exporter (SVG, PDF) / importer", key="export")
        self.export_button.clicked.connect(lambda: self.export_menu(self.export_button))
        register("export", self.export_button)
        # Texte choisi : police, taille, paragraphe (montrés seulement quand la sélection contient un texte ; la barre
        # « Texte » disparaît quand ils sont cachés).
        self.font_button = PaletteTextButton("font", "Police", "Police", cells=4)
        self.font_button.clicked.connect(lambda: self.font_menu(self.font_button))
        register("font", self.font_button)
        self.size_button = PaletteTextButton("size", "12 pt", "Corps (taille du texte)", cells=2)
        self.size_button.clicked.connect(lambda: self.size_menu(self.size_button))
        register("size", self.size_button)
        self.paragraph_button = PaletteTextButton("paragraph", "Paragraphe", "Alignement, interligne, approche, style",
                                                  cells=3)
        self.paragraph_button.clicked.connect(lambda: self.paragraph_menu(self.paragraph_button))
        register("paragraph", self.paragraph_button)
        self.bars.restore()
        self._text_widgets = (self.font_button, self.size_button, self.paragraph_button)
        for widget in self._text_widgets:
            widget.hide()

        from settings_theme import _text_label
        from .layers import LayersPanel
        self.layers, layers = _panel(pane, True)
        layers.setContentsMargins(10, 10, 10, 10)
        layers.setSpacing(6)
        head = QWidget(self.layers)
        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout(head)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_text_label("Calques", "card_title"), 1)
        add = _GlyphButton("plus", "Nouveau calque", head, 26)
        add.set_library_icon("general/ajouter_02")
        add.clicked.connect(ctl.new_layer)
        row.addWidget(add)
        layers.addWidget(head)
        self.layer_list = LayersPanel(ctl, self.layers)
        layers.addWidget(self.layer_list)
        self.layers.hide()
        self.layers_open = False
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.sync)
        ctl.stateChanged.connect(self._sync_timer.start)
        self.hide()

    # Compatibilité : les anciennes barres sont des barres flottantes du gestionnaire (celle qui porte « Sélection » et celle
    # qui porte l'opacité) ; une barre supprimée ou vidée par l'utilisateur est remplacée par un widget caché.
    def _bar_of(self, key: str):
        bar = self.bars.manager.bar_of(key)
        return bar if bar is not None else self._no_bar

    @property
    def tools(self):
        return self._bar_of("select")

    @property
    def control(self):
        return self._bar_of("opacity")

    # -- visibilité / place --
    def show(self):
        self.bars.set_visible(True)
        self.bars.raise_all()
        self.layers.setVisible(self.layers_open)
        self.sync()
        self.place()

    def hide(self):
        self.bars.set_visible(False)
        self.layers.hide()

    def brush_menu(self, anchor):
        """Profils de largeur (sélection), pointe calligraphique (curseurs en direct : sélection + Pinceau), forme
        de tache."""
        from settings_menu import menu_row
        from . import brushes
        ctl = self.ctl
        menu = _menu(self.pane, "ill_brushes")
        menu.aboutToHide.connect(ctl.scene.commit_live)
        profiles = menu.addMenu("Profil de largeur")
        for key, (label, profile) in brushes.PROFILES.items():
            profiles.addAction(label).triggered.connect(lambda _c=False, p=profile, k=label: ctl.set_width_profile(
                p, f"Profil : {k}"))
        menu.addSeparator()
        brush = dict(ctl.brush)
        for key, label, low, high, unit, k in (("angle", "Angle de la pointe", 0, 180, "°", 1),
                                               ("roundness", "Rondeur", 2, 100, "%", 100),
                                               ("size", "Taille", 1, 200, "px", 1)):
            slider = _slider(low, high, round(brush[key] * k), unit=unit)

            def moved(v, key=key, k=k):
                brush[key] = v / k
                ctl.set_brush(dict(brush), live=True)
            slider.valueChanged.connect(moved)
            menu_row(menu, label, slider)
        menu.addAction("Appliquer la pointe calligraphique").triggered.connect(lambda: ctl.set_brush(dict(brush)))
        menu.addAction("Retirer le pinceau et le profil").triggered.connect(
            lambda: (ctl.set_brush(None), ctl.set_width_profile([], "Profil : uniforme")))
        menu.addSeparator()
        blob = _slider(2, 300, round(ctl.blob_size), unit="px")
        blob.valueChanged.connect(lambda v: setattr(ctl, "blob_size", float(v)))
        menu_row(menu, "Forme de tache", blob)
        menu.addAction("Vectoriser le contour").triggered.connect(ctl.outline_stroke)
        _popup(menu, anchor)

    def align_menu(self, anchor):
        from .menus import fill_align_menu
        menu = _menu(self.pane, "ill_align")
        fill_align_menu(self.ctl, menu)
        _popup(menu, anchor)

    def _effects(self, anchor):
        from .appearance_ui import effects_menu
        effects_menu(self.ctl, anchor)

    def toggle_layers(self):
        self.layers_open = not self.layers_open
        self.layers.setVisible(self.layers_open)
        self.layers_button.set_on(self.layers_open)
        self.sync_layers()
        self.place()

    def sync_layers(self):
        if self.layers_open:
            self.layer_list.sync()
            self.layers.layout().activate()
            self.layers.resize(self.layers.sizeHint())

    def place(self):
        """Zone des barres (le board à droite de la barre des modules) et panneau Calques : à droite, sous les barres qu'il
        croiserait."""
        margin = 16
        self.bars.set_area(self.pane.left_edge())
        if self.layers.isVisible():
            self.layers.resize(self.layers.sizeHint())
            box = QRect(self.pane.width() - self.layers.width() - margin, self.pane.title_area().bottom() + 8,
                        self.layers.width(), self.layers.height())
            for _ in range(len(self.bars.manager.bars) + 1):
                below = [bar.geometry().bottom() + 8 for bar in self.bars.manager.bars
                         if bar.isVisible() and bar.geometry().intersects(box)]
                if not below or max(below) <= box.top():
                    break
                box.moveTop(max(below))
            self.layers.move(box.topLeft())
            self.layers.raise_()

    # -- état --
    def current_values(self) -> dict:
        """Valeurs montrées : celles du premier objet choisi, sinon le style courant."""
        items = self.ctl.selection()
        return dict(items[-1].data) if items else dict(self.ctl.style)

    def sync(self):
        ctl = self.ctl
        for name, button in self._tool_buttons.items():
            button.set_on(ctl.tool == name)
        values = self.current_values()
        items = ctl.selection()
        texts = ctl.texts()
        if items:
            title = f"{len(items)} objets" if len(items) > 1 else ("Texte" if texts else "Tracé")
        elif ctl.selected_artboard() is not None:
            title = str(ctl.selected_artboard().data.get("name", "Plan de travail"))
        else:
            title = "Aucune sélection"
        self.title.set_text(title)
        self.fill_button.set_swatch(values.get("fill") or "#ffffff")
        self.stroke_button.set_swatch(values.get("stroke") or "#ffffff", ring=min(18.0, 3 + float(
            values.get("stroke_width", 1.0)) * 2) if values.get("stroke") else None)
        self.width_button.set_text(look.to_display(float(values.get("stroke_width", 1.0)))
                                   if values.get("stroke") else "aucun")
        self.opacity.blockSignals(True)
        self.opacity.setValue(round(float(values.get("opacity", 1.0)) * 100))
        self.opacity.blockSignals(False)
        shown = bool(texts)
        if self.font_button.isHidden() == shown:               # barre « Texte » : visible seulement avec un texte choisi
            for widget in self._text_widgets:
                widget.setVisible(shown)
            self.bars.sync()
        if texts:
            from .text import base_font
            first = texts[-1].data
            self.font_button.set_text(base_font(first).family()[:18])
            self.size_button.set_text(look.to_display(float(first["font_size"])))
        self.fill_stroke.update()
        self.layers_button.set_on(self.layers_open)
        if self.layers_open:
            self.layer_list.update()
        self.place()

    # -- menus --
    def pick_color(self, which: str, anchor):
        from settings_widgets import _ColorPickerPopup
        ctl = self.ctl
        current = self.current_values().get(which) or "#000000"
        label = "Fond" if which == "fill" else "Contour"
        from settings_menu import menu_row
        menu = _menu(self.pane, f"ill_{which}")
        grid = _SwatchGrid(paint.SWATCHES, current, 10)
        grid.picked.connect(lambda c: (menu.close(), ctl.set_style(which, c, label)))
        menu_row(menu, "Nuancier", grid)
        used = ctl.document_colors()
        if used:
            mine = _SwatchGrid(used, current, 10)
            mine.picked.connect(lambda c: (menu.close(), ctl.set_style(which, c, label)))
            menu_row(menu, "Du document", mine)
        menu.addAction("Aucun (/)").triggered.connect(lambda: ctl.set_style(which, "", label))
        gradient = self.current_values().get(f"{which}_gradient")
        menu.addSeparator()
        menu.addAction("Dégradé linéaire").triggered.connect(lambda: ctl.set_style(
            f"{which}_gradient", self._gradient_kind(gradient, "linear", current), "Dégradé"))
        menu.addAction("Dégradé radial").triggered.connect(lambda: ctl.set_style(
            f"{which}_gradient", self._gradient_kind(gradient, "radial", current), "Dégradé"))
        if gradient:
            for index, text in ((0, "Couleur de départ du dégradé…"), (-1, "Couleur de fin du dégradé…")):
                menu.addAction(text).triggered.connect(lambda _c=False, i=index: QTimer.singleShot(
                    0, lambda: self._gradient_stop(which, gradient, i, anchor)))
            menu.addAction("Inverser le dégradé").triggered.connect(lambda: ctl.set_style(
                f"{which}_gradient", dict(gradient, stops=[[1.0 - p, c] for p, c in reversed(gradient["stops"])]),
                "Inverser le dégradé"))
            menu.addAction("Sans dégradé").triggered.connect(
                lambda: ctl.set_style(which, gradient["stops"][0][1], label))
        menu.addSeparator()

        def custom():
            popup = _ColorPickerPopup(current if len(current) == 7 else "#000000", label, self.pane)
            popup.colorChanged.connect(lambda c: ctl.live_style(which, c, label))

            def commit(c):
                ctl.live_style(which, c, label)
                ctl.scene.commit_live()

            def cancel():
                had = ctl.scene._live is not None
                ctl.scene.commit_live()
                if had and ctl.selection():
                    ctl.scene.undo.undo()
                ctl.style[which] = current
                ctl.stateChanged.emit()
            popup.committed.connect(commit)
            popup.cancelled.connect(cancel)
            popup.show_near(anchor if isinstance(anchor, QWidget) else self.pane)
        menu.addAction("Couleur…").triggered.connect(lambda: QTimer.singleShot(0, custom))
        _popup(menu, anchor)

    @staticmethod
    def _gradient_kind(current_gradient, kind: str, color: str) -> dict:
        if current_gradient:
            g = paint.new_gradient(kind)
            g["stops"] = [list(s) for s in current_gradient["stops"]]
            return g
        return paint.new_gradient(kind, "#ffffff", "#000000")

    def _gradient_stop(self, which: str, gradient: dict, index: int, anchor):
        from settings_widgets import _ColorPickerPopup
        ctl = self.ctl
        start = gradient["stops"][index][1]

        def with_color(c):
            g = dict(gradient, stops=[list(s) for s in gradient["stops"]])
            g["stops"][index][1] = c
            return g
        popup = _ColorPickerPopup(start if len(start) == 7 else "#" + start[3:], "Couleur du dégradé", self.pane)
        popup.colorChanged.connect(lambda c: ctl.live_style(f"{which}_gradient", with_color(c), "Dégradé"))
        popup.committed.connect(lambda c: (ctl.live_style(f"{which}_gradient", with_color(c), "Dégradé"),
                                           ctl.scene.commit_live()))
        popup.cancelled.connect(lambda: (ctl.scene.commit_live(), ctl.selection() and ctl.scene.undo.undo()))
        popup.show_near(anchor if isinstance(anchor, QWidget) else self.pane)

    def pathfinder_menu(self, anchor):
        ctl = self.ctl
        menu = _menu(self.pane, "ill_pathfinder")
        count = len(ctl.selection())
        for mode in ("unite", "minus_front", "intersect", "exclude"):
            action = menu.addAction(f"Mode de forme : {ctl.PATHFINDER[mode]}")
            action.setEnabled(count > 1)
            action.triggered.connect(lambda _c=False, m=mode: ctl.pathfinder(m))
        menu.addSeparator()
        for mode in ("divide", "trim", "merge", "crop", "minus_back"):
            action = menu.addAction(ctl.PATHFINDER[mode])
            action.setEnabled(count > 1)
            action.triggered.connect(lambda _c=False, m=mode: ctl.pathfinder(m))
        menu.addSeparator()
        action = menu.addAction("Vectoriser le contour")
        action.setEnabled(count > 0)
        action.triggered.connect(ctl.outline_stroke)
        _popup(menu, anchor)

    def font_menu(self, anchor):
        from fm_board.ui import FontPicker
        from settings_menu import menu_row
        from .text import base_font
        ctl = self.ctl
        texts = ctl.texts()
        if not texts:
            return
        menu = _menu(self.pane, "ill_font")
        picker = FontPicker(base_font(texts[-1].data).family())

        def chosen(family):
            menu.close()
            ctl.set_text_attr("font_family", family, "Police")
        picker.chosen.connect(chosen)
        menu_row(menu, "", picker)
        menu.aboutToShow.connect(picker.filter.setFocus)
        _popup(menu, anchor)

    def size_menu(self, anchor):
        ctl = self.ctl
        menu = _menu(self.pane, "ill_font_size")
        for pt in (6, 8, 9, 10, 11, 12, 14, 18, 24, 30, 36, 48, 60, 72, 96, 144):
            menu.addAction(f"{pt} pt").triggered.connect(
                lambda _c=False, v=pt: ctl.set_text_attr("font_size", round(v * model.PT, 4), "Corps"))
        menu.addSeparator()
        menu.addAction("Autre corps…").triggered.connect(lambda: QTimer.singleShot(0, lambda: self._ask_number(
            "font_size", "Corps (pt) :", model.PT, 0.5, 4000.0, "Corps")))
        _popup(menu, anchor)

    def paragraph_menu(self, anchor):
        ctl = self.ctl
        texts = ctl.texts()
        if not texts:
            return
        menu = _menu(self.pane, "ill_paragraph")
        for key, label in (("left", "Aligné à gauche"), ("center", "Centré"), ("right", "Aligné à droite"),
                           ("justify", "Justifié")):
            menu.addAction(label).triggered.connect(
                lambda _c=False, k=key: ctl.set_text_attr("align", k, "Alignement"))
        menu.addSeparator()
        first = texts[-1].data
        menu.addAction("Gras" + (" ✓" if first.get("bold") else "")).triggered.connect(
            lambda: ctl.set_text_attr("bold", not first.get("bold"), "Gras"))
        menu.addAction("Italique" + (" ✓" if first.get("italic") else "")).triggered.connect(
            lambda: ctl.set_text_attr("italic", not first.get("italic"), "Italique"))
        menu.addSeparator()
        menu.addAction("Interligne…").triggered.connect(lambda: QTimer.singleShot(0, lambda: self._ask_number(
            "leading", "Interligne (× le corps) :", 1.0, 0.3, 10.0, "Interligne")))
        menu.addAction("Approche…").triggered.connect(lambda: QTimer.singleShot(0, lambda: self._ask_number(
            "tracking", "Approche (millièmes de cadratin) :", 1.0, -1000.0, 5000.0, "Approche")))
        if first.get("mode") == "path":
            menu.addAction("Départ sur le tracé…").triggered.connect(lambda: QTimer.singleShot(
                0, lambda: self._ask_number("path_offset", "Départ (% de la longueur) :", 0.01, 0.0, 100.0,
                                            "Départ du texte")))
        menu.addSeparator()
        menu.addAction("Créer les contours (Ctrl+Maj+O)").triggered.connect(ctl.outline_text)
        _popup(menu, anchor)

    def _ask_number(self, key: str, label: str, unit: float, low: float, high: float, text: str):
        texts = self.ctl.texts()
        if not texts:
            return
        current = float(texts[-1].data.get(key, 0.0)) / unit
        value, ok = QInputDialog.getDouble(self.pane, "Texte", label, current, low, high, 3)
        if ok:
            self.ctl.set_text_attr(key, round(value * unit, 5), text)

    def width_menu(self):
        ctl = self.ctl
        menu = _menu(self.pane, "ill_stroke_width")
        for pt in STROKE_WIDTHS:
            menu.addAction(f"{pt:g} pt").triggered.connect(
                lambda _c=False, v=pt: ctl.set_style("stroke_width", round(v * model.PT, 4), "Épaisseur"))
        menu.addSeparator()
        for key, text in (("butt", "Extrémité plate"), ("round", "Extrémité arrondie"), ("square", "Extrémité carrée"),
                          ("miter", "Angle en pointe"), ("round_join", "Angle arrondi"), ("bevel", "Angle biseauté")):
            if key in model.CAPS:
                menu.addAction(text).triggered.connect(lambda _c=False, k=key: ctl.set_style("cap", k, "Extrémités"))
            else:
                k = "round" if key == "round_join" else key
                menu.addAction(text).triggered.connect(lambda _c=False, v=k: ctl.set_style("join", v, "Angles"))
        menu.addSeparator()
        menu.addAction("Pointillés 4 / 4").triggered.connect(
            lambda: ctl.set_style("dash", [4.0 * model.PT, 4.0 * model.PT], "Pointillés"))
        menu.addAction("Trait plein").triggered.connect(lambda: ctl.set_style("dash", [], "Pointillés"))
        menu.addAction("Autre épaisseur…").triggered.connect(lambda: QTimer.singleShot(0, self._custom_width))
        _popup(menu, self.width_button)

    def _custom_width(self):
        current = float(self.current_values().get("stroke_width", 1.0)) / model.PT
        value, ok = QInputDialog.getDouble(self.pane, "Contour", "Épaisseur (pt) :", current, 0.0, 1000.0, 3)
        if ok:
            self.ctl.set_style("stroke_width", round(value * model.PT, 4), "Épaisseur")

    def object_menu(self, anchor):
        from .menus import fill_object_menu
        menu = _menu(self.pane, "ill_object")
        fill_object_menu(self.ctl, menu)
        _popup(menu, anchor)

    def artboard_menu(self, anchor):
        ctl = self.ctl
        menu = _menu(self.pane, "ill_artboards")
        for name, w, h in model.ARTBOARD_FORMATS:
            menu.addAction(f"Nouveau : {name}").triggered.connect(
                lambda _c=False, s=(w, h), n=name: ctl.add_artboard(size=s))
        boards = ctl.artboards()
        if boards:
            menu.addSeparator()
            for board in boards:
                menu.addAction(f"Aller à « {board.data.get('name', '')} »").triggered.connect(
                    lambda _c=False, b=board: self.go_to(b))
        _popup(menu, anchor)

    def go_to(self, board):
        view = self.ctl.view
        r = board.scene_rect().adjusted(-40, -40, 40, 40)
        area = view.viewport().rect()
        view.set_zoom(min(area.width() / max(1.0, r.width()), area.height() / max(1.0, r.height())))
        view.center_on(r.center())
        self.ctl.artboard_id = board.item_id
        self.ctl.refresh()
        self.ctl.stateChanged.emit()

    def export_menu(self, anchor):
        ctl = self.ctl
        menu = _menu(self.pane, "ill_export")
        board = ctl.current_artboard()
        if board is not None:
            menu.addAction(f"Exporter « {board.data.get('name', '')} » en SVG…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export(board)))
            menu.addAction("Exporter tous les plans de travail en SVG…").triggered.connect(
                lambda: QTimer.singleShot(0, self._export_all))
        menu.addAction("Exporter tout le dessin en SVG…").triggered.connect(
            lambda: QTimer.singleShot(0, lambda: self._export(None)))
        menu.addSeparator()
        if board is not None:
            menu.addAction(f"Exporter « {board.data.get('name', '')} » en PDF…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export_pdf([board])))
            menu.addAction("Exporter tous les plans de travail en PDF (une page chacun)…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export_pdf(None)))
        else:
            menu.addAction("Exporter le dessin en PDF…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export_pdf(None)))
        if ctl.selection():
            menu.addAction("Exporter la sélection en SVG…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export(None, True)))
        menu.addSeparator()
        menu.addAction("Importer un SVG…").triggered.connect(lambda: QTimer.singleShot(0, self._import))
        menu.addAction("Importer une image ou un SVG… (Ctrl+Maj+P)").triggered.connect(
            lambda: QTimer.singleShot(0, ctl.place_dialog))
        _popup(menu, anchor)

    def _start_dir(self) -> str:
        path = getattr(self.ctl.scene, "board_path", None)
        return str(path.parent) if path is not None and hasattr(path, "parent") else ""

    def _export(self, board, only_selection: bool = False):
        name = (board.data.get("name") if board is not None else "dessin") or "dessin"
        start = self._start_dir()
        target, _f = QFileDialog.getSaveFileName(self.pane, "Exporter en SVG",
                                                 f"{start}/{name}.svg" if start else f"{name}.svg", "SVG (*.svg)")
        if target:
            self.ctl.export_svg(target, board, only_selection)

    def _export_pdf(self, boards):
        name = (boards[0].data.get("name") if boards else "plans de travail") or "dessin"
        start = self._start_dir()
        target, _f = QFileDialog.getSaveFileName(self.pane, "Exporter en PDF",
                                                 f"{start}/{name}.pdf" if start else f"{name}.pdf", "PDF (*.pdf)")
        if target:
            self.ctl.export_pdf(target, boards)

    def _export_all(self):
        folder = QFileDialog.getExistingDirectory(self.pane, "Dossier des SVG", self._start_dir())
        if not folder:
            return
        for board in self.ctl.artboards():
            name = "".join(c if c.isalnum() or c in " -_" else "_" for c in board.data.get("name", "plan")) or "plan"
            self.ctl.export_svg(f"{folder}/{name}.svg", board)

    def _import(self):
        path, _f = QFileDialog.getOpenFileName(self.pane, "Importer un SVG", self._start_dir(), "SVG (*.svg)")
        if path:
            self.ctl.import_svg(path)


def _popup(menu, anchor):
    if isinstance(anchor, QWidget):
        menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))
    else:
        menu.popup(anchor)
