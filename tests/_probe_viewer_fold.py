"""Visionneuse : clic sur l'image ou dans le vide a cote = elle se replie dans la PLANCHE (elle vole dans
sa case) — a gauche, a droite, au-dessus, en dessous ; pellicule coupee (reglage de l'utilisateur)
comme allumee. Clic simple SUR l'image : la planche aussi, aussitot ;
plus de double-clic sur l'image ; glisser l'image zoomee : rien. Dossier d'images temporaire, jamais les reglages reels."""

from _probe_isolate import isolate as _isolate_probe, protected_modules as _probe_modules
_isolate_probe()
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
from browser_core_parts import project_config as _core_project_config, settings as _core_settings
for module in (settings_store, pb, browser_core, _core_project_config, _core_settings, *_probe_modules()):
    for name in ("save_settings", "_save_window_geometry", "save_layout_settings", "_update_layout_setting"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: None)
root = Path(tempfile.mkdtemp())
folder = root / "3d" / "images"
folder.mkdir(parents=True)
for i in range(4):
    image = QImage(800, 600, QImage.Format_RGB32); image.fill(QColor(40 * i, 90, 160)); image.save(str(folder / f"i{i}.png"))
QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
app = QApplication(sys.argv)


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents(); QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete); time.sleep(0.003)


def run(filmstrip: bool):
    settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
    settings["root_path"] = str(root)
    settings["viewer_filmstrip_enabled"] = filmstrip
    pb.apply_all_settings(settings)
    pb.apply_style(app)
    win = pb.PipelineBrowser(root); win._idle_preview_scheduler.timer.stop()
    win.preset_picker.hide()              # ecran virtuel de 800 px : la barre du haut doit y tenir
    win.show(); win.resize(780, 580)
    pump(0.5)
    win._navigate_to(folder); pump(1.0)
    column = [c for c in [*win.columns, *win.group_columns] if c.directory == folder][0]
    column.list.setCurrentRow(1); pump(1.0)
    win.windowHandle().requestActivate(); QTest.qWaitForWindowActive(win, 2000)
    win._set_columns_hidden(True); pump(1.2)
    target = win.scroll.viewport()

    def click_at(pt):
        w = app.widgetAt(target.mapToGlobal(pt))
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.mapFromGlobal(target.mapToGlobal(pt))); pump(0.8)
        return type(w).__name__

    rect = win._focus_overlay.current_rect().toRect()
    print(f"pellicule {'allumee' if filmstrip else 'coupee'} ; image {rect}")
    # Clic SIMPLE sur l'image : la planche aussi, AUSSITOT (plus de double-clic sur l'image).
    on_image = click_at(rect.center())
    assert win._focus_gallery is not None, "clic sur l'image : la planche ne s'ouvre pas"
    print("  sur l'image :", on_image, "-> planche (ok)")
    win._close_focus_gallery(animate=False); pump(0.8)
    # Double-clic sur l'image : plus de retour aux colonnes (le 1er clic ouvre la planche).
    w = app.widgetAt(target.mapToGlobal(rect.center()))
    local = w.mapFromGlobal(target.mapToGlobal(rect.center()))
    QTest.mouseDClick(w, Qt.LeftButton, Qt.NoModifier, local); pump(0.5)
    assert win._project_columns_hidden, "double-clic sur l'image : les colonnes sont revenues"
    print("  double-clic sur l'image -> visionneuse gardee (ok)")
    if win._focus_gallery is not None:
        win._close_focus_gallery(animate=False); pump(0.8)
    win._set_columns_hidden(False); pump(1.2)
    win._set_columns_hidden(True); pump(1.2)
    # Glisser l'image zoomee : elle se deplace, pas de planche.
    overlay = win._focus_overlay
    overlay.zoom_by(3.0); pump(0.8)
    centre = overlay.current_rect().toRect().center() if not overlay.zoomed() else overlay.rect().center()
    QTest.mousePress(overlay, Qt.LeftButton, Qt.NoModifier, centre)
    QTest.mouseMove(overlay, centre + QPoint(60, 0))
    QTest.mouseRelease(overlay, Qt.LeftButton, Qt.NoModifier, centre + QPoint(60, 0))
    pump(0.4)
    assert win._focus_gallery is None, "glisser l'image zoomee a ouvert la planche"
    print("  glisser l'image zoomee -> pas de planche (ok)")
    overlay.zoom_reset(); pump(0.8)
    rect = win._focus_overlay.current_rect().toRect()
    area = win._viewer_area()
    sides = {"gauche": QPoint(max(area.left() + 5, rect.left() - 60), rect.center().y()),
             "droite": QPoint(min(area.right() - 5, rect.right() + 60), rect.center().y()),
             "dessus": QPoint(rect.center().x(), max(area.top() + 5, rect.top() - 30)),
             "dessous": QPoint(rect.center().x(), min(area.bottom() - 5, rect.bottom() + 30))}
    for name, pt in sides.items():
        if rect.contains(pt):
            print("  ", name, ": pas de vide de ce cote (image jusqu'au bord)")
            continue
        if win._filmstrip is not None and win._filmstrip.isVisible() and win._filmstrip.geometry().contains(pt):
            print("  ", name, ": c'est la pellicule (un clic y choisit une image)")
            continue
        widget = click_at(pt)
        opened = win._focus_gallery is not None
        print(f"  {name:7} {pt.x()},{pt.y()} sur {widget:20} -> planche {opened}")
        assert opened, f"clic a {name} : la planche ne s'ouvre pas"
        win._close_focus_gallery(animate=False); pump(0.6)
        assert win._focus_gallery is None and win._focus_overlay.isVisible()
    win.close(); pump(0.3)


run(False)
run(True)
print("OK")
