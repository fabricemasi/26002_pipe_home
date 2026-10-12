"""Usage : python tests/_probe_obj_select.py  (racine reelle).
Descend Type=BIB > Projets=obj puis clique un fichier de la colonne OBJ et affiche
ce que l'inspecteur montre (chemin, boutons image/turntable)."""
import os, sys, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QElapsedTimer
APP = QApplication.instance() or QApplication([])
import pipeline_browser as p
import app_style

settings = p.load_settings(); p.apply_all_settings(settings)
app_style.apply_style(APP)
w = p.PipelineBrowser(Path(settings["root_path"]))
w._idle_preview_scheduler.timer.stop()
w.setGeometry(10, 10, 1700, 900); w.show()


def pump(ms):
    t = QElapsedTimer(); t.start()
    while t.elapsed() < ms:
        APP.processEvents()


def pick(col, name):
    for i in range(col.list.count()):
        if Path(col.list.item(i).data(p.ROLE_PATH)).name.lower() == name.lower():
            col.list.setCurrentRow(i)
            pump(900)
            return True
    return False


def dump(tag):
    print(f"--- {tag}")
    print("colonnes:", [(c.column_title, c.list.count(), str(c.current_path() and c.current_path().name)) for c in w.columns])
    d = w.detail
    print("detail.path:", getattr(d, "_path", None) or getattr(d, "current_path", None))
    for n in ("kind",):
        print("kind:", d.values[n].text())
    print("path_label:", w.path_label.text())
    print("media row visible:", d.preview_media_row.isVisible(), {k: b.isVisible() for k, b in d.preview_media_buttons.items()})
    return
    for n in dir(d):
        if "media" in n.lower() and "button" in n.lower() or n in ("image_button", "turntable_button"):
            try:
                print(n, getattr(d, n).isVisible())
            except Exception:
                pass


pump(500)
print("types:", pick(w.columns[0], "BIB"))
print("projets:", pick(w.columns[1], "obj"))
dump("apres obj")
print("groupe:", [(c._group_kind, c.list.count()) for c in w.group_columns])
last = w.group_columns[0] if w.group_columns else w.columns[-1]
print("clic feuilles:", pick(last, "feuilles_01.obj"))
dump("apres feuilles")
