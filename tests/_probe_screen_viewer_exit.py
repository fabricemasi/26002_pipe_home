"""Compte les images REELLEMENT affichees a l'ecran (voir _screen_strip.py) quand on sort de la
visionneuse : les colonnes doivent reapparaitre en FONDU (plusieurs images), depuis l'image en grand
comme depuis la planche. Fenetre native, dossier d'images temporaire, jamais les reglages reels."""
import copy, os, subprocess, sys, tempfile, time
from pathlib import Path
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
for i in range(6):
    image = QImage(1600, 1000, QImage.Format_RGB32); image.fill(QColor(40 * i, 120, 200 - 30 * i)); image.save(str(folder / f"i{i}.png"))
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.002)


settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.setGeometry(40, 40, 1500, 850); win.show(); win.raise_(); win.activateWindow()
pump(0.8)
win._navigate_to(folder); pump(1.2)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]


def open_viewer(name):
    lst = column.list
    item = next(lst.item(i) for i in range(lst.count()) if Path(lst.item(i).data(pb.ROLE_PATH)).name == name)
    lst.setCurrentItem(item); pump(0.6)
    win._view_in_viewer(folder / name); pump(1.5)          # meme chemin que le double-clic
    assert win._project_columns_hidden


def measure(label):
    vp = win.scroll.viewport()
    g = vp.mapToGlobal(vp.rect().topLeft()); r = win.devicePixelRatioF()
    y, x, width = int((g.y() + 140) * r), int(g.x() * r), int(vp.width() * r)
    out = os.path.join(tempfile.gettempdir(), f"_strip_viewer_{label}.txt")
    proc = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "_screen_strip.py"),
                             str(x), str(y), str(width), out, "2.0"])
    pump(0.7)
    t0 = time.perf_counter()
    QTest.mousePress(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
    QTest.mouseRelease(vp, Qt.BackButton, Qt.NoModifier, vp.rect().center())
    vals = []
    end = time.perf_counter() + 1.2
    while time.perf_counter() < end:
        f = win._columns_fade
        vals.append((round((time.perf_counter() - t0) * 1000), None if f is None else round(f._value, 2)))
        app.processEvents(); time.sleep(0.002)
    proc.wait()
    print("  fondu (ms, valeur):", vals[:1], [v for v in vals if v[1] is not None][::8][:12], flush=True)
    rows = [(float(a), b) for a, b in (l.split() for l in open(out).read().splitlines())]
    os.remove(out)
    seg = [(t, h) for t, h in rows if t0 <= t <= t0 + 0.8]
    changes = [seg[i][0] for i in range(1, len(seg)) if seg[i][1] != seg[i - 1][1]]
    span = (changes[-1] - changes[0]) * 1000 if len(changes) > 1 else 0
    print("  ecran (ms):", [round((c - t0) * 1000) for c in changes][:20], flush=True)
    print(f"{label}: {len(changes)} images a l'ecran sur {span:.0f} ms", flush=True)
    return len(changes)


open_viewer("i1.png")
a = measure("depuis l'image")
open_viewer("i3.png")
win._step_focus_image(1); pump(0.4); win._step_focus_image(1); pump(1.2)   # synchro au repos faite
c = measure("depuis l'image, apres 2 images")
open_viewer("i2.png")
win._toggle_focus_gallery(); pump(1.0)
b = measure("depuis la planche")
win.close(); pump(0.3)
print("OK" if min(a, b, c) >= 5 else "PAS DE FONDU")
