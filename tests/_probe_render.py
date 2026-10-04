"""Capture toutes les pages de la fenetre de reglages (comparaison avant/apres refactor)."""
import os, sys, hashlib
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, os.getcwd())
from PySide6.QtWidgets import QApplication, QStackedWidget, QScrollArea
APP = QApplication.instance() or QApplication([])
import app_style
app_style.apply_style(APP)
import settings_window as sw

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
w = sw.SettingsWindow()
w.resize(1100, 900)
w.show()
APP.processEvents()
# Onglet Colonnes visite une fois : sa sous-page Type est construite a la demande.
w._on_main_tab_changed(1); w._on_main_tab_changed(0)
APP.processEvents()
import settings_layout as sl
for _ in range(4):
    for sec in w.findChildren(sl._Section) + w.findChildren(sl._SubSection):
        sec.set_collapsed(False)
    APP.processEvents()
stacks = w.findChildren(QStackedWidget)
# toutes les combinaisons d'onglets : on parcourt chaque pile independamment
shots = 0
def grab_all(tag):
    global shots
    for k, area in enumerate(w.findChildren(QScrollArea)):
        inner = area.widget()
        if inner is None or not area.isVisible():
            continue
        img = inner.grab().toImage()
        path = os.path.join(out, f"{tag}_scroll{k}.png")
        img.save(path)
        shots += 1
grab_all("base")
for si, stack in enumerate(stacks):
    for idx in range(stack.count()):
        stack.setCurrentIndex(idx)
        APP.processEvents()
        for sec in w.findChildren(sl._Section) + w.findChildren(sl._SubSection):
            sec.set_collapsed(False)
        APP.processEvents()
        grab_all(f"stack{si}_{idx}")
    stack.setCurrentIndex(0)
w._on_main_tab_changed(1)
for idx in range(w._columns_stack.count()):
    w._on_columns_tab_changed(idx)
    APP.processEvents()
    for _ in range(3):
        for sec in w.findChildren(sl._Section) + w.findChildren(sl._SubSection):
            sec.set_collapsed(False)
        APP.processEvents()
    for area in w.findChildren(QScrollArea):
        if area.widget() is not None and area.isVisible() and area is not w._content_scroller:
            area.widget().grab().toImage().save(os.path.join(out, f"columns_{idx}.png")); shots += 1
print("shots", shots)
