"""Planche ouverte : un clic A COTE du tableau (dans la planche hors du tableau, ou dans le fond autour
d'elle) = retour aux colonnes (sortie depuis la planche : aucun fichier selectionne) ; un clic dans le
tableau choisit toujours l'image. Dossier temporaire, jamais les reglages reels."""
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
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
for i in range(4):
    image = QImage(400, 300, QImage.Format_RGB32); image.fill(QColor.fromHsv(i * 60, 150, 180))
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
win.show(); win.resize(1400, 850)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)


def enter_gallery():
    column.list.setCurrentRow(1); pump(1.0)
    win._set_columns_hidden(True); pump(1.2)
    win._open_focus_gallery(); pump(1.2)
    return win._focus_gallery


def click_global(point):
    widget = app.widgetAt(point)
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, widget.mapFromGlobal(point)); pump(1.5)
    return type(widget).__name__


gallery = enter_gallery()
table = gallery._table_rect()
viewport = gallery.viewport()
print("planche", gallery.geometry(), "| tableau (viewport)", table, "| viewport", viewport.geometry())
cases = {
    "dans la planche, a gauche du tableau": viewport.mapToGlobal(QPoint(max(2, table.left() - 40) if table.left() > 40 else -5, table.center().y())),
    "fond autour de la planche (marge gauche)": win.scroll.viewport().mapToGlobal(QPoint(6, gallery.geometry().center().y())),
}
for name, point in cases.items():
    widget = click_global(point)
    print(f"{name} (sur {widget}) -> colonnes : {not win._project_columns_hidden} | fichier selectionne : {column.list.currentItem() is not None and column.list.currentItem().isSelected()}")
    assert not win._project_columns_hidden, name
    gallery = enter_gallery()
# clic DANS le tableau : l'image est choisie, la visionneuse reste
cell = gallery.visualItemRect(gallery.item(2)).center()
click_global(gallery.viewport().mapToGlobal(cell))
print("clic dans le tableau -> visionneuse :", win._project_columns_hidden, "| planche fermee :", win._focus_gallery is None)
assert win._project_columns_hidden and win._focus_gallery is None
win.close(); pump(0.3)
print("OK")
