"""Visionneuse sur un dossier avec une planche PureRef (3 images) : on regarde sa 3e image puis on
revient aux colonnes : la colonne selectionne la planche et l'INSPECTEUR montre cette 3e image (pas la
premiere). Dossier et cache temporaires, jamais les reglages reels."""
import copy, os, sys, tempfile, time
from pathlib import Path
from unittest import mock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QBuffer, QByteArray, QCoreApplication, QEvent, QIODevice, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
import preview_column as pc
for module in (settings_store, pb, browser_core):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
pb.PipelineBrowser.on_activated = lambda self, path: None
cache = Path(tempfile.mkdtemp())
pc.FILE_IMAGE_DISK_CACHE_DIR = cache
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "refs"
folder.mkdir(parents=True)


def encoded(color: str) -> bytes:
    image = QImage(400, 300, QImage.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray(); buffer = QBuffer(data); buffer.open(QIODevice.WriteOnly); image.save(buffer, "PNG")
    return bytes(data)


for name, color in (("a.png", "#336699"), ("z.png", "#996633")):
    QImage(400, 300, QImage.Format_RGB32).save(str(folder / name))
pur = folder / "m_planche.pur"
pur.write_bytes(b"\x00\x00\x00\x08" + "1.10".encode("utf-16-be") + b"\x00" * 40 + encoded("#ff0000") + b"\x00x\x00"
                + encoded("#00ff00") + b"\x00y\x00" + encoded("#0000ff") + b"\x00" * 16)
pc.extract_pur_embedded_images(pur, pur.stat().st_mtime)
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
lst = column.list
row = next(i for i in range(lst.count()) if Path(lst.item(i).data(pb.ROLE_PATH)).name == pur.name)
lst.setCurrentRow(row); pump(1.0)
win._set_columns_hidden(True); pump(1.2)
names = [pb.focus.display_name(p) for p in win._viewer_paths] if hasattr(pb, "focus") else []
print("visionneuse :", [Path(p).name for p in win._viewer_paths], "| en cours", win._viewer_index)
for _ in range(2):
    win._step_focus_image(1); pump(0.5)                     # 3e image de la planche
shown = Path(win._viewer_paths[win._viewer_index])
print("image regardee :", shown.name, "->", win._pur_sources.get(str(shown)))
for wait in (0.1, 1.5):                                     # retour aussitot, puis apres la synchro
    win._set_columns_hidden(False); pump(1.5)
    detail = win.detail
    print(f"retour (apres {wait}s) : colonne -> {column.current_path().name if column.current_path() else None} | "
          f"inspecteur -> planche {Path(detail._pur_image_path).name if detail._pur_image_path else None}, "
          f"image {detail._pur_image_index + 1}")
    assert column.current_path() == pur and detail._pur_image_index == 2, "l'inspecteur ne montre pas l'image regardee"
    win._set_columns_hidden(True); pump(1.2)
    pump(wait)
win.close(); pump(0.3)
print("OK")
