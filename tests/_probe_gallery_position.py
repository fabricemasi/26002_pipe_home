"""Planche : choisir une image (en haut ou en bas de l'ecran) puis revenir a la planche = la planche
revient A LA MEME POSITION (meme premiere ligne visible), jamais recentree sur l'image. Image en cours
sortie de la vue (fleches dans la visionneuse) : defilement minimal, pas de recentrage. Dossier temporaire,
jamais les reglages reels."""
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
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(60):
    image = QImage(400, 300, QImage.Format_RGB32); image.fill(QColor.fromHsv((i * 23) % 360, 150, 180))
    image.save(str(folder / f"i{i:02d}.png"))
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
win.show(); win.resize(1200, 800)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
column.list.setCurrentRow(0); pump(1.0)
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
win._set_columns_hidden(True); pump(1.2)


def open_gallery():
    win._open_focus_gallery(); pump(1.2)
    return win._focus_gallery


gallery = open_gallery()
print("planche :", gallery._cols, "colonnes,", gallery._visible_rows, "lignes visibles sur", gallery._rows)
assert gallery._rows > gallery._visible_rows + 2, "la planche doit defiler pour ce test"
for where in ("bas", "haut"):
    gallery._scroll_to_row(3); pump(0.2)
    first = gallery.first_visible_row()
    row = first + (gallery._visible_rows - 1 if where == "bas" else 0)
    item = gallery.item(row * gallery._cols + 1)
    QTest.mouseClick(gallery.viewport(), Qt.LeftButton, Qt.NoModifier, gallery.visualItemRect(item).center())
    pump(1.2)
    assert win._focus_gallery is None, "l'image choisie n'est pas passee au centre"
    gallery = open_gallery()
    print(f"image en {where} de l'ecran : premiere ligne {first} -> {gallery.first_visible_row()}")
    assert gallery.first_visible_row() == first, "la planche a ete recentree"
# Image en cours sortie de la vue (fleches) : defilement minimal
gallery._scroll_to_row(0); pump(0.2)
first = gallery.first_visible_row()
item = gallery.item(0)
QTest.mouseClick(gallery.viewport(), Qt.LeftButton, Qt.NoModifier, gallery.visualItemRect(item).center()); pump(1.2)
steps = (gallery._visible_rows + 1) * gallery._cols
for _ in range(steps):
    win._step_focus_image(1); pump(0.02)
pump(1.0)
gallery = open_gallery()
current_row = gallery._row_of(gallery.currentItem())
print(f"image avancee jusqu'a la ligne {current_row} : premiere ligne {first} -> {gallery.first_visible_row()} "
      f"(image sur la derniere ligne visible : {current_row == gallery.first_visible_row() + gallery._visible_rows - 1})")
assert current_row == gallery.first_visible_row() + gallery._visible_rows - 1
win.close(); pump(0.3)
print("OK")
