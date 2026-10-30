"""Menus du TEXTE (barre contextuelle) : effets (contour, creux), police (avec la marque), taille, alignement et
listes. Pendant l'édition, police et taille vont à la partie choisie (`text_selection`)."""
from __future__ import annotations

from fm_board.ui import FontPicker, _menu, _slider, _SwatchGrid
from . import design_model as dm, document as doc
from .menus import _live, _popup, style_selection, text_selection


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
        editor = text_selection(ctl)
        if editor is not None:                                  # police d'une partie du texte
            from PySide6.QtGui import QTextCharFormat
            fmt = QTextCharFormat()
            fmt.setFontFamilies([family])
            style_selection(editor, fmt)
            return
        doc.change(ctl.scene, texts, lambda i: i.data.update(font_family=family), "Police")
    picker.chosen.connect(chosen)
    menu_row(menu, "", picker)
    menu.aboutToShow.connect(picker.filter.setFocus)
    fonts = ctl.brand()["fonts"]
    if fonts:
        brand = menu.addMenu("Polices de la marque")
        for family in fonts:
            brand.addAction(family).triggered.connect(lambda _c=False, f=family: chosen(f))
    current = texts[0].data.get("font_family") or ""
    if current and current not in fonts:
        menu.addAction(f"Ajouter « {current} » à la marque").triggered.connect(
            lambda: ctl.brand_add("fonts", current))
    elif current:
        menu.addAction(f"Retirer « {current} » de la marque").triggered.connect(
            lambda: ctl.brand_remove("fonts", current))
    _popup(ctl, menu, anchor)


def size_menu(ctl, anchor, texts):
    from settings_menu import menu_row
    menu = _menu(ctl.pane, "design_font_size")
    current = float(texts[0].data.get("font_size", 48))
    slider = _slider(6, 400, round(current), "px")
    slider.valueChanged.connect(lambda v: _live(ctl, "design_font_size", texts,
                                                lambda i: i.data.update(font_size=float(v)), "Taille du texte"))
    menu_row(menu, "Taille", slider)
    def set_size(size):
        editor = text_selection(ctl)
        if editor is not None:                                  # taille d'une partie du texte
            from PySide6.QtGui import QTextCharFormat, QTextFormat
            fmt = QTextCharFormat()
            fmt.setProperty(QTextFormat.FontPixelSize, int(size))
            style_selection(editor, fmt)
            return
        doc.change(ctl.scene, texts, lambda i: i.data.update(font_size=float(size)), "Taille du texte")
    for size in (12, 16, 24, 32, 48, 64, 96, 128, 200):
        action = menu.addAction(f"{size}")
        action.setCheckable(True)
        action.setChecked(abs(current - size) < 0.01)
        action.triggered.connect(lambda _c=False, s=size: set_size(s))
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
    menu.addSeparator()
    kind = texts[0].data.get("list", "")
    for value, text in (("", "Sans liste"), ("bullet", "Liste à puces"), ("number", "Liste numérotée")):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(kind == value)
        action.triggered.connect(lambda _c=False, v=value: doc.change(
            ctl.scene, texts, lambda i: i.data.update(list=v), "Liste"))
    _popup(ctl, menu, anchor)
