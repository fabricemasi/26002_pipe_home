"""Sortie de la visionneuse : la colonne selectionne la DERNIERE image montree en grand ; sortie
depuis la planche (aucune image en grand) : aucun fichier selectionne dans la colonne.
Dossier d'images temporaire, jamais les reglages reels."""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
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
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
opened = []
pb.open_path = lambda path: opened.append(Path(path))          # jamais de vrai logiciel lance
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(4):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(QColor(40 * i, 90, 160)); image.save(str(folder / f"i{i}.png"))
(folder / "notes.txt").write_text("x")
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
win.show(); win.resize(780, 580)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]


def double_click(name):
    lst = column.list
    item = next(lst.item(i) for i in range(lst.count()) if Path(lst.item(i).data(pb.ROLE_PATH)).name == name)
    lst.scrollToItem(item)
    pos = lst.visualItemRect(item).center()
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(0.3)
    QTest.mouseDClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(1.5)




def selected_name():
    item = column.list.currentItem()
    return Path(item.data(pb.ROLE_PATH)).name if item is not None and item.isSelected() else None


def back_button():
    target = win.scroll.viewport()
    QTest.mousePress(target, Qt.BackButton, Qt.NoModifier, target.rect().center())
    QTest.mouseRelease(target, Qt.BackButton, Qt.NoModifier, target.rect().center()); pump(1.2)
    assert not win._project_columns_hidden, "pas sorti de la visionneuse"


# 1. Image en grand, on avance de 2, sortie aussitot (avant la synchro au repos) : i3 selectionnee.
double_click("i1.png")
assert win._project_columns_hidden
win._step_focus_image(1); pump(0.1); win._step_focus_image(1); pump(0.1)
back_button()
assert selected_name() == "i3.png", selected_name()
print("sortie depuis l'image : i3.png selectionnee (ok)")
# 2. Planche ouverte : sortie = aucun fichier selectionne.
double_click("i0.png")
win._toggle_focus_gallery(); pump(0.8)
assert win._focus_gallery is not None
back_button()
assert selected_name() is None and not column.list.selectedItems(), selected_name()
assert getattr(win.detail, "_current_path", None) in (None, ""), win.detail._current_path
assert win._focus_overlay is None
print("sortie depuis la planche : rien de selectionne (ok)")
# 3. Image choisie dans la planche puis sortie : c'est elle.
double_click("i1.png")
win._toggle_focus_gallery(); pump(0.8)
win._on_gallery_chosen(folder / "i2.png"); pump(1.0)
assert win._focus_gallery is None
back_button()
assert selected_name() == "i2.png", selected_name()
print("choisie dans la planche puis sortie : i2.png selectionnee (ok)")
win.close(); pump(0.3)
print("OK")
