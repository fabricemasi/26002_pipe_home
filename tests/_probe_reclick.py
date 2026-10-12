"""Clic sur la ligne deja selectionnee (PipelineBrowser.on_reclicked) : elle est deselectionnee
et toutes les colonnes ouvertes apres elle se referment (groupe IN/OVER/OUT compris)."""
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
win.on_reclicked(win.columns[-2])   # refs > deep : deep deselectionnee, sa colonne se ferme
print("apres deep :", names())
assert names()[-1] == "refs" and win.columns[-1].current_path() is None, names()
win.on_reclicked(inn)               # IN > refs : le contenu ouvert depuis le groupe se ferme
print("apres IN :", names(), "| selection IN :", inn.current_path())
assert inn.current_path() is None and names()[-1] == "projA" and win.group_columns, names()
win.on_reclicked(win.columns[2])    # sp1 : deselectionne, groupe ferme
print("apres sp1 :", names(), "groupe :", len(win.group_columns))
assert names()[-1] == "projA" and not win.group_columns and win.columns[2].current_path() is None, names()
win.on_reclicked(win.columns[0])    # 3d : tout se referme
print("apres 3d :", names(), "| inspecteur vide :", not getattr(win.detail, "_current_path", None))
assert len(win.columns) == 1 and win.columns[0].current_path() is None, names()
for _ in range(60): APP.processEvents()
print("OK")
