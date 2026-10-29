"""Reglages > Visionneuse (et sa touche, colonne Raccourci), « Effet slide », « Parametres de l'image » > « Diapositives sous l'image en focus » (viewer_filmstrip_enabled) : coupe,
la pellicule disparait en direct, sa bande n'est plus reservee (l'image s'agrandit), les raccourcis
restent ; rallume, elle revient. Dossier d'images temporaire, jamais les reglages reels."""

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
settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(4):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(QColor(40 * i, 90, 160)); image.save(str(folder / f"i{i}.png"))
try:                                            # une photo avec EXIF (Pillow), pour « Prise de vue »
    from PIL import Image
    photo = Image.new("RGB", (1200, 800), (90, 120, 160))
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "Canon", "Canon EOS R5"
    exif.get_ifd(0x8769).update({0x829A: 0.004, 0x829D: 2.8, 0x8827: 400, 0x920A: 50.0})
    photo.save(folder / "i4.jpg", exif=exif, dpi=(300, 300))
except ImportError:
    pass
settings["root_path"] = str(root)
pb.apply_all_settings(settings)
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)
pb.apply_style(app)
win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
win.show(); win.resize(1500, 900)
def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.003)
pump(0.5)
win._navigate_to(folder); pump(1.0)
column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
column.list.setCurrentRow(1); pump(1.0)
win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
win._set_columns_hidden(True); pump(1.2)
strip = lambda: win._filmstrip is not None and win._filmstrip.isVisible()
area_on = win._viewer_area()
print("allume : pellicule", strip(), "| zone", area_on.height(), "| raccourcis", sum(s.isEnabled() for s in win._viewer_keys))
assert strip()
settings["viewer_filmstrip_enabled"] = False
win._apply_settings(copy.deepcopy(settings)); pump(0.6)
area_off = win._viewer_area()
print("coupe : pellicule", strip(), "| zone", area_off.height(), "| raccourcis", sum(s.isEnabled() for s in win._viewer_keys))
assert not strip() and area_off.height() > area_on.height() and any(s.isEnabled() for s in win._viewer_keys)
QTest.keyClick(win, Qt.Key_Right); pump(0.5)
print("fleche droite : rang", win._viewer_index); assert win._viewer_index == 2
win._poll_viewer_cursor(); pump(0.2); assert not strip()       # le mouvement de souris ne la rappelle pas
settings["viewer_filmstrip_enabled"] = True
win._apply_settings(copy.deepcopy(settings)); pump(0.6)
print("rallume : pellicule", strip(), "| zone", win._viewer_area().height())
assert strip() and win._viewer_area().height() == area_on.height()
# Touche reglable (colonne Raccourci) : D par defaut, bascule et enregistre.
saved = []
pb.save_settings = lambda st: saved.append(st.get("viewer_filmstrip_enabled"))
pb.load_settings = lambda *a, **k: copy.deepcopy(settings)
QTest.keyClick(win, Qt.Key_D); pump(0.5)
print("touche D : pellicule", strip(), "| enregistre", saved); assert not strip() and saved == [False]
QTest.keyClick(win, Qt.Key_D); pump(0.5)
assert strip()
settings["viewer_filmstrip_shortcut"] = "Ctrl+B"
win._apply_settings(copy.deepcopy(settings)); pump(0.3)
QTest.keyClick(win, Qt.Key_D); pump(0.3); assert strip()                       # D ne fait plus rien
QTest.keyClick(win, Qt.Key_B, Qt.ControlModifier); pump(0.5)
print("Ctrl+B : pellicule", strip()); assert not strip()
# « Effet slide entre les images » : coupe, l'image change sur place (aucun decalage du ruban).
overlay = win._focus_overlay
QTest.keyClick(win, Qt.Key_Left); app.processEvents()
print("slide allume : decalage", round(overlay.ribbon_offset(), 2)); assert abs(overlay.ribbon_offset()) > 0.05
pump(0.8)
settings["viewer_slide_enabled"] = False
win._apply_settings(copy.deepcopy(settings)); pump(0.3)
before = win._viewer_index
QTest.keyClick(win, Qt.Key_Right); app.processEvents()
print("slide coupe : decalage", round(overlay.ribbon_offset(), 2), "| rang", before, "->", win._viewer_index)
assert overlay.ribbon_offset() == 0 and win._viewer_index == before + 1
strip_pos = win._filmstrip._pos
print("pellicule (slide coupe) : position", round(strip_pos, 2), "-> glisse :", win._filmstrip.gliding())
assert win._filmstrip.gliding() and before <= strip_pos < before + 1   # elle defile, pas de saut
pump(0.6)
print("pellicule au repos :", round(win._filmstrip._pos, 2)); assert win._filmstrip._pos == win._viewer_index
# « Parametres de l'image » (touche I) : tableau a droite de l'image, qui ne la couvre pas.
QTest.keyClick(win, Qt.Key_I); pump(0.4)
panel = getattr(win, "_info_panel", None)
assert panel is not None and panel.isVisible(), "tableau absent"
panel.wait_done(); pump(0.3)
names = [label for _t, rows in panel.sections() for label, _v in rows]
image = win._focus_overlay._target
print("touche I : tableau", panel.isVisible(), "| sections", [t for t, _r in panel.sections()],
      "| image a droite jusqu'a", round(image.right()), "| tableau a partir de", panel.x())
centre = win._focus_area().center().x()
print("centre de l'image", round(image.center().x()), "| centre de la zone", centre)
assert "Dimensions" in names and image.right() <= panel.x() and abs(image.center().x() - centre) <= 1
QTest.keyClick(win, Qt.Key_End); pump(0.6); panel.wait_done(); pump(0.3)
shot = {label: value for t, rows in panel.sections() if t == "Prise de vue" for label, value in rows}
print("photo :", shot)
assert shot.get("Appareil") == "Canon EOS R5" and shot.get("Exposition") == "1/250 s"
QTest.keyClick(win, Qt.Key_I); pump(0.4)
print("touche I : tableau", panel.isVisible(), "| zone", win._viewer_area().width(), "/", win._focus_area().width())
assert not panel.isVisible() and win._viewer_area().width() == win._focus_area().width()
print("OK")
