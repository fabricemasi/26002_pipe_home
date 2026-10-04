"""Clic sur la ligne deja selectionnee (PipelineBrowser.on_reclicked) :
rien si une seule colonne apres, sinon on ne garde que la suivante."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtWidgets import QApplication
APP = QApplication([])
import app_style; app_style.apply_style(APP)
import pipeline_browser as p
from browser_core import ROLE_PATH

root = Path(tempfile.mkdtemp())
for sub in ("3d/projA/sp1/in/refs/deep", "3d/projA/sp1/blender"):
    (root / sub).mkdir(parents=True)
win = p.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.resize(1600, 800); win.show(); APP.processEvents()

def select(column, name):
    for i in range(column.list.count()):
        it = column.list.item(i)
        if Path(it.data(ROLE_PATH)).name == name:
            column.list.setCurrentItem(it); APP.processEvents(); return
    raise AssertionError(f"{name} absent de {column.column_title}")

def names():
    return [c.directory.name for c in win.columns]

select(win.columns[0], "3d"); select(win.columns[1], "projA"); select(win.columns[2], "sp1")
print("chaine :", names(), "groupe :", [c._group_kind for c in win.group_columns])
inn = next(c for c in win.group_columns if c._group_kind == "in")
select(inn, "refs"); select(win.columns[-1], "deep")
print("ouvert :", names())
before = names()
win.on_reclicked(win.columns[-2])   # refs : une seule colonne apres -> rien
assert names() == before, names()
win.on_reclicked(inn)               # IN : 2 colonnes apres -> garde refs
print("apres IN :", names())
assert names()[-1] == "refs", names()
win.on_reclicked(win.columns[2])    # sp1 : groupe + refs -> garde le groupe
print("apres sp1 :", names(), "groupe :", len(win.group_columns))
assert names()[-1] == "projA" and win.group_columns, names()
win.on_reclicked(win.columns[2])    # plus que le groupe apres -> rien
win.on_reclicked(win.columns[0])    # 3d : Projets + sp1 + groupe -> garde Projets
print("apres 3d :", names(), "groupe :", len(win.group_columns))
assert names()[-1] == "3d" and not win.group_columns, names()
for _ in range(60): APP.processEvents()
print("OK")
