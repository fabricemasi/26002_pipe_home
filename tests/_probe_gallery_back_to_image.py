"""Planche ouverte (la colonne est deselectionnee d'avance, au repos, pour une sortie instantanee) puis
retour a l'IMAGE : la colonne et l'inspecteur la reprennent ; sortie ensuite vers les colonnes : l'image
repart vers l'inspecteur et reste selectionnee. Sortie directe depuis la planche : aucun fichier
selectionne. Dossier temporaire, jamais les reglages reels."""
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
for module in (settings_store, pb, browser_core):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
pb.PipelineBrowser.on_activated = lambda self, path: None
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(6):
    image = QImage(800, 500, QImage.Format_RGB32); image.fill(QColor.fromHsv(i * 50, 150, 190))
    image.save(str(folder / f"i{i}.png"))
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.003)


settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.preset_picker.hide()
win.show(); win.resize(780, 560)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
column.list.setCurrentRow(2); pump(1.0)
win._set_columns_hidden(True); pump(1.2)
win._step_focus_image(1); pump(1.5)                       # image i3, synchro faite
win._open_focus_gallery(); pump(2.0)                      # au repos : colonne deselectionnee d'avance
print("planche ouverte : deselection d'avance", win._gallery_deselected, "| colonne :", column.current_path())
assert win._gallery_deselected and column.current_path() is None
win._close_focus_gallery(); pump(1.6)                     # retour a l'image
print("retour a l'image : colonne ->", column.current_path().name if column.current_path() else None,
      "| inspecteur ->", Path(win.detail._current_path).name if win.detail._current_path else None)
assert column.current_path() is not None and column.current_path().name == "i3.png"
win._set_columns_hidden(False); pump(1.5)
print("sortie depuis l'image : colonnes", not win._project_columns_hidden, "| selection",
      column.current_path().name if column.current_path() else None)
assert not win._project_columns_hidden and column.current_path().name == "i3.png"
# Sortie directe depuis la planche : aucun fichier selectionne.
win._set_columns_hidden(True); pump(1.2)
win._open_focus_gallery(); pump(2.0)
win._set_columns_hidden(False); pump(1.5)
print("sortie depuis la planche : selection", column.current_path())
assert column.current_path() is None
win.close(); pump(0.3)
print("OK")
