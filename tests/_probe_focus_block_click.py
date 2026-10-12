"""Colonnes Focus : un clic sur le TITRE ou l'IMAGE d'un bloc (PreviewColumn._defocus_click_filter)
defocalise le dossier de sa vraie colonne, comme un re-clic dessus (PipelineBrowser.on_reclicked)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
APP = QApplication([])
import app_style; app_style.apply_style(APP)
import pipeline_browser as p
from browser_core import ROLE_PATH
root = Path(tempfile.mkdtemp())
for sub in ("3d/projA/sp1/in/refs", "3d/projA/sp1/blender"):
    (root / sub).mkdir(parents=True)
win = p.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.resize(1600, 900); win.show(); APP.processEvents()
def select(column, name):
    for i in range(column.list.count()):
        it = column.list.item(i)
        if Path(it.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(it); APP.processEvents(); return
    raise AssertionError(name)
def settle():
    for _ in range(30): APP.processEvents()
    QTest.qWait(500)
def state():
    return [c.directory.name for c in win.columns], [c.current_path() and c.current_path().name for c in win.columns], len(win.image_preview_columns)
select(win.columns[0], "3d"); select(win.columns[1], "projA"); select(win.columns[2], "sp1"); settle()
print("depart :", state())
blocks = [c.preview_layout.itemAt(0).widget() for c in win.image_preview_columns]
print("blocs :", [type(b).__name__ for b in blocks])
# 1) clic sur l'IMAGE du bloc du bas (sous-projet sp1)
b = blocks[-1]
QTest.mouseClick(b.image, Qt.LeftButton, Qt.NoModifier, b.image.rect().center()); settle()
print("apres image sp1 :", state())
assert win.columns[2].current_path() is None
select(win.columns[2], 'sp1'); settle(); print('reselection :', state())
b = win.image_preview_columns[0].preview_layout.itemAt(0).widget()
from PySide6.QtWidgets import QLabel
label = b._title_bar.findChild(QLabel)
print("titre :", label.text())
QTest.mouseClick(label, Qt.LeftButton, Qt.NoModifier, label.rect().center()); settle()
print("apres titre projA :", state())
assert win.columns[1].current_path() is None
print("OK")
