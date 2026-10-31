"""Menu « Effets » de la barre de contrôle (panneau Aspect d'Illustrator réduit à un menu) : ajouter un effet,
régler chacun par des curseurs EN DIRECT (une étape par geste : `scene.live_change`, terminée à la fermeture du menu),
couleur, activer / désactiver, supprimer ; contours supplémentaires ; décomposer l'aspect. Briques : menus et
curseurs des réglages (`fm_board.ui._menu`, `_slider`, `settings_menu.menu_row`, `_ColorPickerPopup`)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from fm_board.ui import _menu, _slider
from . import appearance as ap


def _slider_row(menu, label, low, high, value, unit, on_change):
    from settings_menu import menu_row
    slider = _slider(low, high, round(value), unit=unit)
    slider.valueChanged.connect(on_change)
    menu_row(menu, label, slider)


def _color(ctl, anchor, current: str, apply_live, label: str):
    from settings_widgets import _ColorPickerPopup
    popup = _ColorPickerPopup(current if len(current) == 7 else "#" + current[-6:], label, ctl.pane)
    popup.colorChanged.connect(apply_live)
    popup.committed.connect(lambda c: (apply_live(c), ctl.scene.commit_live()))
    popup.cancelled.connect(lambda: (ctl.scene.commit_live(), ctl.scene.undo.undo()))
    popup.show_near(anchor if isinstance(anchor, QWidget) else ctl.pane)


def effects_menu(ctl, anchor):
    menu = _menu(ctl.pane, "ill_effects")
    menu.aboutToHide.connect(ctl.scene.commit_live)
    items = ctl.selection()
    if not items:
        menu.addAction("Choisir d'abord un objet").setEnabled(False)
        _show(menu, anchor)
        return
    first = items[-1].data
    add = menu.addMenu("Ajouter un effet")
    for kind in ap.ORDER:
        action = add.addAction(ap.LABELS[kind])
        action.setEnabled(ap.effect(first, kind) is None)
        action.triggered.connect(lambda _c=False, k=kind: ctl.add_effect(k))
    for e in first.get("effects") or []:
        kind = e["type"]
        sub = menu.addMenu(ap.LABELS[kind] + ("" if e.get("on", True) else " (désactivé)"))
        for key, label, low, high, unit in ap.PARAMS[kind]:
            value = e[key] * (100 if unit == "%" else 1)
            _slider_row(sub, label, low, high, value, unit,
                        lambda v, k=kind, key=key, u=unit: ctl.set_effect(k, key, v / 100.0 if u == "%" else float(v)))
        if "color" in e:
            sub.addAction("Couleur…").triggered.connect(lambda _c=False, k=kind, c=e["color"]: QTimer.singleShot(
                0, lambda: _color(ctl, anchor, c, lambda col: ctl.set_effect(k, "color", col), ap.LABELS[k])))
        sub.addAction("Désactiver" if e.get("on", True) else "Activer").triggered.connect(
            lambda _c=False, k=kind: ctl.toggle_effect(k))
        sub.addAction("Supprimer").triggered.connect(lambda _c=False, k=kind: ctl.remove_effect(k))
    menu.addSeparator()
    action = menu.addAction("Ajouter un contour")
    action.setEnabled(len(first.get("extra_strokes") or []) < ap.MAX_STROKES)
    action.triggered.connect(ctl.add_extra_stroke)
    for n, stroke in enumerate(first.get("extra_strokes") or []):
        sub = menu.addMenu(f"Contour supplémentaire {n + 1}")
        _slider_row(sub, "Épaisseur", 0, 200, stroke["width"], "px",
                    lambda v, i=n: ctl.set_extra_stroke(i, "width", float(v)))
        _slider_row(sub, "Opacité", 0, 100, stroke["opacity"] * 100, "%",
                    lambda v, i=n: ctl.set_extra_stroke(i, "opacity", v / 100.0))
        sub.addAction("Couleur…").triggered.connect(lambda _c=False, i=n, c=stroke["color"]: QTimer.singleShot(
            0, lambda: _color(ctl, anchor, c, lambda col: ctl.set_extra_stroke(i, "color", col), "Contour")))
        sub.addAction("Supprimer").triggered.connect(lambda _c=False, i=n: ctl.remove_extra_stroke(i))
    menu.addSeparator()
    menu.addAction("Décomposer l'aspect").triggered.connect(ctl.expand_appearance)
    _show(menu, anchor)


def _show(menu, anchor):
    if isinstance(anchor, QWidget):
        menu.popup(anchor.mapToGlobal(anchor.rect().bottomLeft()))
    else:
        menu.popup(anchor)
