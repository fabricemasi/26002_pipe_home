"""Menus du module Illustrator : clic droit dans le canvas, menu « Objet » de la barre de contrôle. Libellés et
raccourcis d'Illustrator (menu Objet : Disposition, Grouper, Verrouiller, Masquer, Tracé > Joindre, Tracé
transparent ; Transformer > Symétrie / Rotation)."""
from __future__ import annotations

from fm_board.ui import _menu


def fill_object_menu(ctl, menu):
    items = ctl.selection()
    has = bool(items)

    def add(text, slot, enabled=True):
        action = menu.addAction(text)
        action.setEnabled(enabled)
        action.triggered.connect(slot)

    add("Premier plan (Ctrl+Maj+])", lambda: ctl.arrange("front"), has)
    add("En avant (Ctrl+])", lambda: ctl.arrange("forward"), has)
    add("En arrière (Ctrl+[)", lambda: ctl.arrange("backward"), has)
    add("Arrière-plan (Ctrl+Maj+[)", lambda: ctl.arrange("back"), has)
    menu.addSeparator()
    add("Grouper (Ctrl+G)", lambda: ctl.set_group(True), len(items) > 1)
    add("Dissocier (Ctrl+Maj+G)", lambda: ctl.set_group(False), any(i.data.get("group") for i in items))
    menu.addSeparator()
    transform_menu(ctl, menu, has)
    add("Symétrie horizontale", lambda: ctl.flip(True), has)
    add("Symétrie verticale", lambda: ctl.flip(False), has)
    add("Rotation de 90° horaire", lambda: ctl.rotate_selection(90), has)
    add("Rotation de 90° antihoraire", lambda: ctl.rotate_selection(-90), has)
    menu.addSeparator()
    add("Joindre (Ctrl+J)", ctl.join_selection, has)
    add("Vectoriser le contour", ctl.outline_stroke, has)
    add("Convertir en tracés CAD", ctl.convert_to_cad, bool(ctl.shapes()))
    add("Décomposer l'aspect", ctl.expand_appearance, has)
    has_image = any(type(i).__name__ == "IllImageItem" for i in items)
    add("Recadrer l'image (masque)", ctl.crop_with_mask, has_image)
    trace_menu(ctl, menu, has_image)
    add("Créer un tracé transparent (Ctrl+8)", lambda: ctl.make_compound(True), len(items) > 1)
    add("Défaire le tracé transparent (Ctrl+Alt+Maj+8)", lambda: ctl.make_compound(False),
        any(len(i.data["subpaths"]) > 1 for i in items))
    menu.addSeparator()
    masked = bool(ctl.masked_groups())
    add("Créer un masque d'écrêtage (Ctrl+7)", lambda: ctl.make_mask("clip"), len(items) > 1)
    add("Créer un masque d'opacité", lambda: ctl.make_mask("opacity"), len(items) > 1)
    add("Annuler le masque (Ctrl+Alt+7)", ctl.release_mask, masked)
    add("Inverser le masque d'opacité", ctl.invert_opacity_mask, masked)
    menu.addSeparator()
    add("Verrouiller la sélection (Ctrl+2)", ctl.lock_selection, has)
    add("Tout déverrouiller (Ctrl+Alt+2)", ctl.unlock_all)
    add("Masquer la sélection (Ctrl+3)", ctl.hide_selection, has)
    add("Tout afficher (Ctrl+Alt+3)", ctl.show_all)
    menu.addSeparator()
    add("Copier le style", ctl.copy_style, has)
    add("Coller le style", ctl.paste_style, has and bool(ctl.style_clipboard))
    add("Mode Tracés (Ctrl+Y)", ctl.toggle_outline)


def fill_align_menu(ctl, menu):
    """Panneau Alignement : sur la sélection (un seul objet / groupe : sur son plan de travail)."""
    count = len(ctl.selection())
    for how, label in (("left", "Aligner à gauche"), ("hcenter", "Centrer horizontalement"),
                       ("right", "Aligner à droite"), ("top", "Aligner en haut"),
                       ("vcenter", "Centrer verticalement"), ("bottom", "Aligner en bas")):
        action = menu.addAction(label)
        action.setEnabled(count > 0)
        action.triggered.connect(lambda _c=False, h=how: ctl.align(h))
    menu.addSeparator()
    for axis, spacing, label in (("h", False, "Répartir les centres horizontalement"),
                                 ("v", False, "Répartir les centres verticalement"),
                                 ("h", True, "Répartir l'espacement horizontal"),
                                 ("v", True, "Répartir l'espacement vertical")):
        action = menu.addAction(label)
        action.setEnabled(count > 2)
        action.triggered.connect(lambda _c=False, a=axis, s=spacing: ctl.distribute(a, s))


def transform_menu(ctl, menu, has: bool):
    from PySide6.QtCore import QPointF
    sub = menu.addMenu("Transformer")
    sub.setEnabled(has)
    sub.addAction("Transformer de nouveau (Ctrl+D)").triggered.connect(ctl.transform_again)
    sub.addAction("Déplacer…").triggered.connect(ctl.move_dialog)

    def center():
        rect = ctl.selection_rect()
        return rect.center() if rect is not None else QPointF()
    sub.addAction("Rotation…").triggered.connect(lambda: ctl.tools["rotate"].dialog(center()))
    sub.addAction("Mise à l'échelle…").triggered.connect(lambda: ctl.tools["scale"].dialog(center()))
    sub.addAction("Symétrie…").triggered.connect(lambda: ctl.tools["reflect"].dialog(center()))
    menu.addAction("Repères commentés (Ctrl+U)" + (" ✓" if ctl.smart_guides else "")).triggered.connect(
        ctl.toggle_smart_guides)
    align = menu.addMenu("Aligner et répartir")
    fill_align_menu(ctl, align)


def trace_menu(ctl, menu, enabled: bool):
    """Vectoriser l'image : préréglages (noms d'Illustrator) et réglages par curseurs (seuil, couleurs, détail,
    précision, bruit, angles, lissage), comme le panneau Vectorisation de l'image. Un préréglage change le mode et
    les couleurs, et garde les réglages fins choisis (détail, précision, bruit, angles, lissage)."""
    from settings_menu import menu_row
    from fm_board.ui import _slider
    from . import trace as tr
    sub = menu.addMenu("Vectoriser l'image")
    sub.setEnabled(enabled)
    for key, (label, _values) in tr.PRESETS.items():
        sub.addAction(label).triggered.connect(lambda _c=False, k=key: (
            ctl.trace_settings.update(tr.settings_for(k, **{name: ctl.trace_settings[name] for name in tr.FINE_KEYS
                                                            if name in ctl.trace_settings})),
            ctl.trace_image()))
    sub.addSeparator()
    s = ctl.trace_settings
    for key, label, low, high, unit, k in (("threshold", "Seuil (noir et blanc)", 0, 255, "", 1),
                                           ("colors", "Couleurs", 2, 30, "", 1),
                                           ("detail", "Détail (px)", 100, 1500, "px", 1),
                                           ("fidelity", "Précision : écart max (dixièmes de px)", 2, 50, "", 10),
                                           ("noise", "Bruit (px²)", 0, 400, "", 1),
                                           ("corner", "Angles : virage mini (°)", 10, 170, "°", 1),
                                           ("smooth", "Lissage (dixièmes de px)", 0, 30, "", 10)):
        slider = _slider(low, high, round(float(s[key]) * k), unit=unit)
        slider.valueChanged.connect(lambda v, key=key, k=k: s.update({key: v / k if k != 1 else v}))
        menu_row(sub, label, slider)
    sub.addAction("Vectoriser avec ces réglages").triggered.connect(lambda: ctl.trace_image())


def open_context_menu(ctl, global_pos, scene_pos):
    """Clic droit : l'objet sous la souris est choisi s'il ne l'était pas (comme Illustrator)."""
    item = ctl.object_at(scene_pos)
    if item is not None and not item.isSelected():
        ctl.select(ctl.group_of(item))
    menu = _menu(ctl.pane, "ill_context")
    fill_object_menu(ctl, menu)
    if ctl.selection():
        menu.addSeparator()
        menu.addAction("Supprimer (Suppr)").triggered.connect(ctl.delete_selection)
    menu.popup(global_pos)
