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
    add("Symétrie horizontale", lambda: ctl.flip(True), has)
    add("Symétrie verticale", lambda: ctl.flip(False), has)
    add("Rotation de 90° horaire", lambda: ctl.rotate_selection(90), has)
    add("Rotation de 90° antihoraire", lambda: ctl.rotate_selection(-90), has)
    menu.addSeparator()
    add("Joindre (Ctrl+J)", ctl.join_selection, has)
    add("Vectoriser le contour", ctl.outline_stroke, has)
    add("Décomposer l'aspect", ctl.expand_appearance, has)
    add("Recadrer l'image (masque)", ctl.crop_with_mask,
        any(type(i).__name__ == "IllImageItem" for i in items))
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
