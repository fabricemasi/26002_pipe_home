"""Interface du module Illustrator (briques du board et des réglages, aucun style inventé) :
- barre d'OUTILS à gauche (`fm_board.ui._bar` vertical) : outils groupés comme la barre d'Illustrator, puis le
  témoin fond / contour (`FillStroke`) ;
- barre de CONTRÔLE en haut : fond, contour, épaisseur, opacité de la sélection (ou du style courant), symétries,
  plans de travail, export / import SVG.
Contenu mis à jour seulement quand la sélection ou l'outil change (`stateChanged`, regroupé par passage de boucle)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from fm_board.ui import _bar, _GlyphButton, _menu, _slider, _TextButton
from . import model

TOOL_GROUPS = [
    [("select", "ill_select"), ("direct", "ill_direct")],
    [("pen", "ill_pen"), ("add_anchor", "ill_add_anchor"), ("delete_anchor", "ill_delete_anchor"),
     ("convert", "ill_convert")],
    [("rect", "ill_rect"), ("ellipse", "ill_ellipse"), ("polygon", "ill_polygon"), ("star", "ill_star"),
     ("line", "ill_line"), ("pencil", "ill_pencil")],
    [("artboard", "ill_artboard"), ("eyedropper", "ill_eyedropper"), ("hand", "ill_hand"), ("zoom", "ill_zoom")],
]
STROKE_WIDTHS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0, 30.0, 50.0]


class FillStroke(QWidget):
    """Témoin fond / contour d'Illustrator : carré plein (fond) et carré évidé (contour), celui au premier plan
    dessus ; clic = le mettre au premier plan, clic sur celui qui y est déjà = choisir sa couleur ; « aucun » = barre
    rouge."""

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setFixedSize(QSize(40, 40))
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("Fond et contour (X : premier plan, Maj+X : intervertir, D : par défaut, / : aucun) ; "
                        "clic sur celui au premier plan : sa couleur")

    def _rects(self):
        return QRectF(2, 2, 24, 24), QRectF(14, 14, 24, 24)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        fill_rect, stroke_rect = self._rects()
        values = self.ctl.ui.current_values()
        order = ["stroke", "fill"] if self.ctl.focus == "fill" else ["fill", "stroke"]
        for which in order:
            rect = fill_rect if which == "fill" else stroke_rect
            color = values.get(which, "")
            p.setPen(QPen(QColor("#9a9a9a"), 1))
            if which == "fill":
                p.setBrush(QColor(color) if color else QColor("#ffffff"))
                p.drawRect(rect)
            else:
                p.setBrush(QColor("#ffffff") if not color else Qt.NoBrush)
                p.drawRect(rect)
                if color:
                    p.setPen(QPen(QColor(color), 6))
                    p.drawRect(rect.adjusted(3, 3, -3, -3))
                    p.setPen(QPen(QColor("#9a9a9a"), 1))
                    p.setBrush(QColor("#2b2b2b"))
                    p.drawRect(rect.adjusted(7, 7, -7, -7))
            if not color:
                p.setPen(QPen(QColor("#e0281e"), 2))
                p.drawLine(rect.bottomLeft() + QPointF(2, -2), rect.topRight() + QPointF(-2, 2))
        p.end()

    def mousePressEvent(self, event):
        fill_rect, stroke_rect = self._rects()
        pos = QPointF(event.position())
        front, back = (fill_rect, stroke_rect) if self.ctl.focus == "fill" else (stroke_rect, fill_rect)
        which = self.ctl.focus if front.contains(pos) else (
            ("stroke" if self.ctl.focus == "fill" else "fill") if back.contains(pos) else None)
        if which is None:
            return
        if which != self.ctl.focus:
            self.ctl.focus = which
            self.ctl.stateChanged.emit()
            return
        self.ctl.ui.pick_color(which, self)


class IllustratorChrome(QObject):
    def __init__(self, pane, ctl):
        super().__init__(pane)
        self.pane = pane
        self.ctl = ctl
        self.tools, tools = _bar(pane, True)
        tools.setAlignment(Qt.AlignHCenter)
        self._tool_buttons = {}
        for index, group in enumerate(TOOL_GROUPS):
            if index:
                tools.addSpacing(8)
            for name, glyph in group:
                button = _GlyphButton(glyph, ctl.tools[name].label, self.tools, 30)
                button.clicked.connect(lambda _c=False, n=name: ctl.set_tool(n))
                tools.addWidget(button, 0, Qt.AlignHCenter)
                self._tool_buttons[name] = button
        tools.addSpacing(8)
        self.fill_stroke = FillStroke(ctl, self.tools)
        tools.addWidget(self.fill_stroke, 0, Qt.AlignHCenter)
        swap = _GlyphButton("ill_swap", "Intervertir fond et contour (Maj+X)", self.tools, 26)
        swap.clicked.connect(ctl.swap_fill_stroke)
        tools.addWidget(swap, 0, Qt.AlignHCenter)

        self.control, bar = _bar(pane, False)
        self.title = _TextButton("Aucune sélection", "Sélection", self.control)
        self.title.setEnabled(False)
        bar.addWidget(self.title)
        bar.addSpacing(6)
        self.fill_button = _GlyphButton("fill", "Fond", self.control, 30)
        self.fill_button.clicked.connect(lambda: self.pick_color("fill", self.fill_button))
        self.stroke_button = _GlyphButton("border", "Contour", self.control, 30)
        self.stroke_button.clicked.connect(lambda: self.pick_color("stroke", self.stroke_button))
        self.width_button = _TextButton("1 pt", "Épaisseur du contour", self.control, 64)
        self.width_button.clicked.connect(self.width_menu)
        for widget in (self.fill_button, self.stroke_button, self.width_button):
            bar.addWidget(widget)
        bar.addSpacing(6)
        self.opacity = _slider(0, 100, 100, unit="%")
        self.opacity.setParent(self.control)
        self.opacity.setToolTip("Opacité")
        self.opacity.valueChanged.connect(lambda v: ctl.live_style("opacity", v / 100.0, "Opacité"))
        bar.addWidget(self.opacity)
        bar.addSpacing(6)
        self.object_button = _TextButton("Objet", "Disposition, groupe, symétries, tracés", self.control)
        self.object_button.clicked.connect(lambda: self.object_menu(self.object_button))
        self.board_button = _TextButton("Plans de travail", "Nouveau plan de travail, formats", self.control)
        self.board_button.clicked.connect(lambda: self.artboard_menu(self.board_button))
        self.export_button = _GlyphButton("ill_export", "Exporter / importer en SVG", self.control, 30)
        self.export_button.clicked.connect(lambda: self.export_menu(self.export_button))
        for widget in (self.object_button, self.board_button, self.export_button):
            bar.addWidget(widget)
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.setInterval(0)
        self._sync_timer.timeout.connect(self.sync)
        ctl.stateChanged.connect(self._sync_timer.start)
        self.hide()

    # -- visibilité / place --
    def show(self):
        self.tools.show()
        self.control.show()
        self.sync()
        self.place()

    def hide(self):
        self.tools.hide()
        self.control.hide()

    def place(self):
        margin = 16
        for panel in (self.tools, self.control):
            panel.layout().activate()
            panel.resize(panel.sizeHint())
            panel.raise_()
        self.tools.move(margin, max(margin + 50, (self.pane.height() - self.tools.height()) // 2))
        top = self.pane.title_area().bottom() + 8
        self.control.move(max(margin, (self.pane.width() - self.control.width()) // 2), top)

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
        if items:
            self.title.setText(f"{len(items)} objet{'s' if len(items) > 1 else ''}"
                               if len(items) > 1 else "Tracé")
        elif ctl.selected_artboard() is not None:
            self.title.setText(str(ctl.selected_artboard().data.get("name", "Plan de travail")))
        else:
            self.title.setText("Aucune sélection")
        self.fill_button.set_swatch(values.get("fill") or "#ffffff")
        self.stroke_button.set_swatch(values.get("stroke") or "#ffffff", ring=min(18.0, 3 + float(
            values.get("stroke_width", 1.0)) * 2) if values.get("stroke") else None)
        width = float(values.get("stroke_width", 1.0)) / model.PT
        self.width_button.setText(f"{width:g} pt" if values.get("stroke") else "aucun")
        self.opacity.blockSignals(True)
        self.opacity.setValue(round(float(values.get("opacity", 1.0)) * 100))
        self.opacity.blockSignals(False)
        self.fill_stroke.update()
        self.place()

    # -- menus --
    def pick_color(self, which: str, anchor):
        from settings_widgets import _ColorPickerPopup
        ctl = self.ctl
        current = self.current_values().get(which) or "#000000"
        label = "Fond" if which == "fill" else "Contour"
        menu = _menu(self.pane, f"ill_{which}")
        menu.addAction("Aucun (/)").triggered.connect(lambda: ctl.set_style(which, "", label))
        menu.addAction("Noir").triggered.connect(lambda: ctl.set_style(which, "#000000", label))
        menu.addAction("Blanc").triggered.connect(lambda: ctl.set_style(which, "#ffffff", label))

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
        if ctl.selection():
            menu.addAction("Exporter la sélection en SVG…").triggered.connect(
                lambda: QTimer.singleShot(0, lambda: self._export(None, True)))
        menu.addSeparator()
        menu.addAction("Importer un SVG…").triggered.connect(lambda: QTimer.singleShot(0, self._import))
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
