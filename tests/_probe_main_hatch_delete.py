"""Suppression de lignes d'un board DANS la vraie fenetre principale, avec les VRAIS reglages de l'utilisateur
(lus seulement : aucune ecriture), sur une copie du board.   QT_QPA_PLATFORM=windows python tests/_probe_main_delete.py <board.mro>"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import os, random, shutil, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting", "save_live_state"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
src = Path(sys.argv[1])
root = Path(tempfile.mkdtemp())
copy = root / src.name
shutil.copy(src, copy)
settings = settings_store.load_settings()
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication(sys.argv)
pb.apply_style(app)
window = pb.PipelineBrowser(root)
window.show()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.002)


pump(1.0)
print("ouverture :", window._open_board(copy))
pump(1.0)
pane = window._board
view = pane.view
print("gpu", getattr(view, "gpu", None) is not None, "cad", pane.cad is not None and pane.cad.active)
pane.toggle_cad(True); pump(1.0)
print('cad', pane.cad.active)
from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QMouseEvent
vp = view.viewport()
def move(doc):
    at = QPointF(pane.cad.doc_to_view(doc))
    app.sendEvent(vp, QMouseEvent(QEvent.MouseMove, at, vp.mapToGlobal(at), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    pump(0.08)
ctl = pane.cad
# centre de la grande piece (octogone) : milieu des lignes blanches
items = [i for i in ctl.cad_items() if i.kind == "cad_line"]
xs = [p[0] for i in items for p in i.points()]; ys = [p[1] for i in items for p in i.points()]
inside = ((-3779.5 - 3779.5 / 2), 1000.0)
def key(text):
    for ch in text: QTest.keyClick(view, ch)
    QTest.keyClick(view, Qt.Key_Return)
pane.view.set_zoom(0.1); pump(0.5)
key("H"); QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, ctl.doc_to_view(inside).toPoint()); pump(0.3); key("")
hs = [i for i in ctl.cad_items() if i.kind == "cad_hatch"]
print("hachures", len(hs), "pur", view.gpu.pure if view.gpu else None, flush=True)
if hs:
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, ctl.doc_to_view(inside).toPoint()); pump(0.2)
    print("selection", [i.kind for i in ctl.selection()], "pick_all", [i.kind for i in ctl.pick_all(ctl.doc_to_view(inside))], "cmd", ctl.command, flush=True)
    h = hs[0]; print("dist", h.distance_to(inside), "reach", h._reach, "bounds", h.doc_bounds(), "inside", h.data.get("hatch_pattern"), h.data.get("hatch_spacing"), flush=True)
    QTest.keyClick(view, Qt.Key_Delete); pump(1.0)
    print("apres", len([i for i in ctl.cad_items() if i.kind == "cad_hatch"]), "pur", view.gpu.pure if view.gpu else None, flush=True)
    for d in [inside, (inside[0] + 300, inside[1] + 300), (inside[0] - 500, inside[1])]:
        move(d)
        print("curseur", ctl.cursor_doc, "vp", vp.cursor().shape(), "snap", ctl.hover_snap, flush=True)
print("fini")
