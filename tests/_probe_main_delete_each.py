"""Suppression de lignes d'un board DANS la vraie fenetre principale, avec les VRAIS reglages de l'utilisateur
(lus seulement : aucune ecriture), sur une copie du board.   QT_QPA_PLATFORM=windows python tests/_probe_main_delete.py <board.mro>"""
import os, random, shutil, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
for module in (settings_store, pb, browser_core):
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
ids = [i for i in pane.scene.items() if getattr(i, "CAD", False)]
order = sorted(ids, key=lambda i: i.zValue())
for k, it in enumerate(order):
    if it.scene() is None:
        continue
    pane.scene.clearSelection()
    it.setSelected(True)
    view.setFocus()
    c = view.mapFromScene(it.sceneBoundingRect().center())
    QTest.mouseMove(view.viewport(), QPoint(c.x(), c.y())); pump(0.4)
    QTest.keyClick(view, Qt.Key_Delete)
    pump(1.3)
    print(k, getattr(it, "data", {}).get("id", "?") if hasattr(it, "data") else "", flush=True)
    pane.scene.undo.undo()
    pump(0.3)
print("fini sans plantage")
