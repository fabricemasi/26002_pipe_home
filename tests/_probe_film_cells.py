"""Visionneuse, diapositives ET planche : Reglages > Visionneuse > Tableau / Sous cellule image / texte changes
dans la fenetre v2 OUVERTE -> la pellicule et la planche changent ; clic droit (vrai clic systeme, en mode
natif) -> menu Tableau / Cellule image / Cellule texte -> tableau a la volee qui change aussi. Dossier
temporaire, jamais les reglages reels. Lancer : QT_QPA_PLATFORM=windows python tests/_probe_film_cells.py"""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, ctypes, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QPoint
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
import settings_window_v2 as v2
import settings_quick_style as qs
import ui_state
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules(), v2, qs):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
for module in (v2, pb, qs):
    module.load_settings = lambda: copy.deepcopy(settings)
root = Path(tempfile.mkdtemp()); folder = root / "3d" / "images"; folder.mkdir(parents=True)
for i in range(6):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(QColor(40 * i, 90, 160)); image.save(str(folder / f"i{i}.png"))
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv); pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.show(); win.resize(1500, 900)
def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.003)
pump(0.5); win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
column.list.setCurrentRow(1); pump(1.0)
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
win._set_columns_hidden(True); pump(1.2)
strip = win._filmstrip
win._open_focus_gallery(); pump(1.0)
gallery = win._focus_gallery
print("planche", gallery is not None and gallery.isVisible())
before = gallery.viewport().grab().toImage()
# 1. fenetre de reglages v2
win.open_settings_v2(); pump(0.5)
dialog = win._settings_dialog_v2
page = dialog.stack.currentWidget()
for title in ("Visionneuse", "Sous cellule texte"):
    for node in page.findChildren(v2._LazyNode):
        if node.node.title == title:
            node.set_collapsed(False)
pump(0.3)
specs = {sp.key: w for st in dialog.stores.values() for sp, w in st.get("specs", ()) if not isinstance(sp, str)}
specs["viewer_film_text_cell_bg"].setValue("#ffaa2020"); dialog._mark_dirty(); pump(0.5)
after = gallery.viewport().grab().toImage()
print("reglages v2 -> APPLIED", ui_state.APPLIED_SETTINGS.get("viewer_film_text_cell_bg"), "| planche changee", before != after)
assert before != after
dialog.hide(); pump(0.2)
# 2. vrai clic droit sur la planche (mode natif)
shown = []
class FakeMenu(pb.QMenu):
    def exec(self, *a, **k):
        shown.append([x.text() for x in self.actions()])
        return self.actions()[-1]            # Cellule texte
pb.QMenu = FakeMenu
if os.environ.get("QT_QPA_PLATFORM") == "windows":
    win.raise_(); win.activateWindow(); pump(0.3)
    g = gallery.viewport().mapToGlobal(gallery.viewport().rect().center())
    dpr = win.devicePixelRatioF()
    ctypes.windll.user32.SetCursorPos(int(g.x() * dpr), int(g.y() * dpr)); pump(0.2)
    ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0); pump(0.05)
    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0); pump(0.5)
else:
    win._filmstrip_menu(QPoint(10, 10)); pump(0.3)
print("menu :", shown)
assert shown
window = win._film_style_window
print("tableau a la volee :", window is not None and window.isVisible(), window.titlebar.title if hasattr(window.titlebar, "title") else "")
field = next(w for sp, w in window._fields if sp.key == "viewer_film_text_cell_bg")
before = gallery.viewport().grab().toImage()
field.setValue("#ff20aa20"); window._emit(); pump(0.6)
after = gallery.viewport().grab().toImage()
print("a la volee -> APPLIED", ui_state.APPLIED_SETTINGS.get("viewer_film_text_cell_bg"), "| planche changee", before != after)
assert before != after
# 3. Ctrl + bordure image | texte dans la planche
item = gallery.item(0)
cell, box = gallery.tile_boxes(gallery.visualItemRect(item))
h0 = gallery.label_height()
line = QPoint(cell.center().x(), box.bottom() + 1)
QTest.mousePress(gallery.viewport(), Qt.LeftButton, Qt.ControlModifier, line)
QTest.mouseMove(gallery.viewport(), line - QPoint(0, 30))
QTest.mouseRelease(gallery.viewport(), Qt.LeftButton, Qt.ControlModifier, line - QPoint(0, 30)); pump(0.4)
print("hauteur du texte", h0, "->", gallery.label_height(), "| enregistree", settings.get("viewer_gallery_text_height"),
      ui_state.APPLIED_SETTINGS.get("viewer_gallery_text_height"))
assert gallery.label_height() > h0
gallery.viewport().grab().save(os.environ.get("SHOT", "nul.png")); print("OK")
