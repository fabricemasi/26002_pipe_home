"""Menu EXPORTER du module Design : format (PNG, JPEG, PDF, SVG), pages (toutes, courante, plage), taille, qualité,
fond transparent, fond perdu et traits de coupe ; puis le fichier (`render.export_pages`)."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog

from fm_board.ui import _menu, _slider
from .menus import _popup


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
