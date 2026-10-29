"""Visionneuse ouverte sur un dossier avec des planches PureRef : un bouton par .pur, a la suite
des autres boutons, qui ouvre le fichier (logiciel par defaut) ; plus de boutons quand les colonnes reviennent.
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
for n in ("refs_a.pur", "moodboard.pur"):
    (folder / n).write_bytes(b"PureRef junk")
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


double_click("i2.png")
assert win._project_columns_hidden, "la visionneuse ne s'ouvre pas"
shown = [b for b in win._pur_buttons if b.isVisible()]
assert sorted(b._text for b in shown) == ["moodboard.pur", "refs_a.pur"], [b._text for b in shown]
vp = win.scroll.viewport()
for b in shown:
    assert b.geometry().right() <= vp.width() and b.y() < 40, b.geometry()
    assert b.width() > b.fontMetrics().horizontalAdvance(b._text), "nom rogne"
others = [r for r in win._button_rects() if not any(r == b.geometry() for b in shown)]
assert others, "aucun autre bouton"
assert min(b.x() for b in shown) > max(r.right() for r in others), "pas a la suite des autres boutons"
assert all(b.y() == min(r.top() for r in others) for b in shown), "pas sur leur ligne"
print("autres boutons :", [r.getRect() for r in others])
assert not shown[0].geometry().intersects(shown[1].geometry())
print("boutons :", [(b._text, b.geometry().getRect()) for b in shown])
QTest.mouseClick(shown[0], Qt.LeftButton); pump(0.2)
assert opened and opened[-1].name == shown[0]._text, opened
print("clic ->", opened[-1].name, "(ok)")
win._toggle_focus_gallery(); pump(0.8)
assert all(b.isVisible() for b in shown), "planche : boutons perdus"
win._toggle_focus_gallery(); pump(0.8)
# Bouton « precedent » de la souris, clic SUR l'image (l'overlay le recoit avant la fenetre).
target = win._focus_overlay if win._focus_overlay is not None and win._focus_overlay.isVisible() else vp
QTest.mousePress(target, Qt.BackButton, Qt.NoModifier, target.rect().center())
QTest.mouseRelease(target, Qt.BackButton, Qt.NoModifier, target.rect().center()); pump(1.0)
assert not win._project_columns_hidden, "le bouton precedent de la souris ne sort pas de la visionneuse"
print("bouton precedent de la souris -> colonnes (ok)")
assert not any(b.isVisible() for b in win._pur_buttons), "boutons restes avec les colonnes"
win.close(); pump(0.3)
print("OK")
