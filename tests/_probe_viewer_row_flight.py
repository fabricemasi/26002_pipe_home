"""Double-clic sur une ligne de colonne -> visionneuse : l'image PART DE L'APERCU DE LA LIGNE (pas de
l'inspecteur) et, une fois au centre, son retour vise l'inspecteur ; une planche PureRef s'ouvre aussi dans
la visionneuse, un fichier 3D sans apercu garde son logiciel ; Reglages > Visionneuse > « Animation des
diapositives » coupee = les cases apparaissent en simple fondu. Dossier temporaire, jamais les reglages reels."""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
import copy, os, sys, tempfile, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import settings_store, browser_core
import pipeline_browser as pb
import ui_state
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
opened = []
pb.open_path = lambda path: opened.append(Path(path))
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(4):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(QColor(40 * i, 90, 160)); image.save(str(folder / f"i{i}.png"))
(folder / "scene.ma").write_text("//Maya ASCII\n")         # 3D jamais rendue : pas d'apercu
(folder / "vide.pur").write_bytes(b"PureRef")              # planche illisible : pas d'apercu
REAL_PUR = Path("F:/PIPELINE/3D/_char/octopus/in/ref/octopus.v001.pur")   # vraie planche (machine de l auteur)
if REAL_PUR.exists():
    import shutil
    shutil.copy(REAL_PUR, folder / "refs.pur")
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
win.show(); win.resize(1400, 800)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
lst = column.list


def item_of(name):
    return next(lst.item(i) for i in range(lst.count()) if Path(lst.item(i).data(pb.ROLE_PATH)).name == name)


def double_click(name, wait=1.5):
    item = item_of(name)
    lst.scrollToItem(item)
    pos = lst.visualItemRect(item).center()
    QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(0.6)
    QTest.mouseDClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(wait)


# 1. Vol depuis la ligne
started = []
real_overlay = pb.FocusOverlay


class Spy(real_overlay):
    def __init__(self, parent, pixmap, source, target, *a, **k):
        started.append(QRect(source.toRect()))
        super().__init__(parent, pixmap, source, target, *a, **k)


pb.FocusOverlay = Spy
item = item_of("i2.png")
pos = lst.visualItemRect(item).center()
QTest.mouseClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(0.8)
row_src = column.preview_source(folder / "i2.png")
inspector = win._focus_source()
print("apercu de la ligne :", row_src and row_src[1], "| inspecteur :", inspector and inspector[1])
assert row_src is not None and inspector is not None
QTest.mouseDClick(lst.viewport(), Qt.LeftButton, Qt.NoModifier, pos); pump(1.5); pump(1.0)
print("masque", win._project_columns_hidden, "vols", started, "overlay", win._focus_overlay)
assert win._project_columns_hidden and started, "pas de vol"
viewport = win.scroll.viewport()
row_rect = QRect(viewport.mapFromGlobal(row_src[1].topLeft()), row_src[1].size())
print("depart du vol :", started[-1], "| ligne :", row_rect)
assert abs(started[-1].center().x() - row_rect.center().x()) <= 2 and abs(started[-1].center().y() - row_rect.center().y()) <= 2
home = win._focus_overlay._source.toRect()
print("retour vise :", home, "| inspecteur :", inspector[1])
assert abs(home.center().x() - inspector[1].center().x()) <= 2, "le retour ne vise pas l'inspecteur"
win._set_columns_hidden(False); pump(1.2)
assert not win._project_columns_hidden

# 2. 3D sans apercu : logiciel ; planche PureRef : visionneuse
double_click("scene.ma")
print("scene.ma ->", "logiciel" if opened and opened[-1].name == "scene.ma" else "visionneuse")
assert opened and opened[-1].name == "scene.ma" and not win._project_columns_hidden
double_click("vide.pur")
print("vide.pur (sans apercu) ->", "logiciel" if opened and opened[-1].name == "vide.pur" else "rien !")
assert opened and opened[-1].name == "vide.pur" and not win._project_columns_hidden
if (folder / "refs.pur").exists():
    double_click("refs.pur", wait=4.0)
    print("refs.pur ->", "visionneuse" if win._project_columns_hidden else "logiciel",
          "| image montree :", win._viewer_paths[win._viewer_index].name if win._viewer_paths else None)
    assert win._project_columns_hidden and all(p.name != "refs.pur" for p in opened)
    win._set_columns_hidden(False); pump(1.2)

# 3. Animation des diapositives coupee
double_click("i1.png")
ui_state.APPLIED_SETTINGS["viewer_gallery_ripple_enabled"] = False
win._open_focus_gallery(); pump(0.2)
print("vague coupee -> fondu :", win._focus_gallery._ripple_fade, "| animation en cours :", win._focus_gallery._ripple_origin is not None)
assert win._focus_gallery._ripple_fade and win._focus_gallery._ripple_origin is not None
win._close_focus_gallery(animate=False); pump(0.3)
ui_state.APPLIED_SETTINGS["viewer_gallery_ripple_enabled"] = True
win._open_focus_gallery(); pump(0.1)
print("vague (active) :", win._focus_gallery._ripple_origin is not None and not win._focus_gallery._ripple_fade)
assert win._focus_gallery._ripple_origin is not None and not win._focus_gallery._ripple_fade
win.close(); pump(0.3)
print("OK")
