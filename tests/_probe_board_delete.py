"""Sonde des PLANTAGES a l'effacement d'elements du board (Miro), en vraie fenetre Windows :

    QT_QPA_PLATFORM=windows QT_QPA_FONTDIR=C:\\Windows\\Fonts .venv/Scripts/python.exe -X faulthandler tests/_probe_board_delete.py [gpu]

Chaque scenario est affiche avant d'etre joue : la derniere ligne ecrite avant un plantage nomme le coupable."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402
import fm_board as board  # noqa: E402
from fm_board import model  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402

GPU = "gpu" in sys.argv[1:]


def settle(seconds=0.15):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        APP.processEvents()
        time.sleep(0.003)


def log(text):
    print(text, flush=True)


def main():
    app_style.apply_style(APP)
    folder = Path(tempfile.mkdtemp())
    path = board.create_board_file(folder / "b")
    host = QWidget()
    host.resize(1300, 860)
    host.move(100, 60)
    host.show()
    settings = {"board_opengl": True} if GPU else {}
    pane = board_ui.BoardPane(host, settings=settings)
    pane.set_module("miro")
    pane.open(path)
    pane.resize(1300, 860)
    pane.show()
    settle(0.5)
    scene, view = pane.scene, pane.view
    if GPU:
        log(f"GPU : {view.set_gpu(True)} {type(view.viewport()).__name__}")
        settle(0.5)
    img = folder / "i.png"
    q = QImage(400, 300, QImage.Format_RGB32)
    q.fill(QColor("teal"))
    q.save(str(img))

    def mk(kind, **v):
        return scene.add_new(model.new_item(kind, **v), select=False)

    def vp(item):
        return view.mapFromScene(item.scene_rect().center())

    def press_delete(items, key=Qt.Key_Delete):
        scene.clearSelection()
        for i in items:
            i.setSelected(True)
        settle(0.05)
        view.setFocus()
        QTest.keyClick(view.viewport(), key)
        settle(0.1)

    def undo_redo(n=2):
        for _ in range(n):
            scene.undo.undo()
            settle(0.05)
            scene.undo.redo()
            settle(0.05)
        scene.undo.undo()
        settle(0.05)

    scenarios = []

    def scenario(f):
        scenarios.append(f)
        return f

    @scenario
    def sticky():
        s = mk("sticky", x=0, y=0, text="hello")
        press_delete([s])
        undo_redo()

    @scenario
    def text_backspace():
        t = mk("text", x=300, y=0, text="abc")
        press_delete([t], Qt.Key_Backspace)
        undo_redo()

    @scenario
    def image():
        item = view.add_image_file(str(img), QPointF(0, 300)) if hasattr(view, "add_image_file") else None
        if item is None:
            name = board.serialization.import_asset(path, img) if hasattr(board.serialization, "import_asset") else None
            log(f"  (image par asset {name})")
            if name is None:
                return
            item = mk("image", x=0, y=300, w=400, h=300, asset=name)
        settle(0.3)
        press_delete([item])
        undo_redo()

    @scenario
    def connector_and_ends():
        a = mk("sticky", x=-600, y=0)
        b = mk("sticky", x=-300, y=0)
        c = mk("connector", start={"item": a.item_id}, end={"item": b.item_id})
        scene.refresh_links()
        settle(0.1)
        press_delete([a])
        undo_redo()
        press_delete([c])
        undo_redo()
        press_delete([a, b])
        undo_redo()

    @scenario
    def frame_with_content():
        f = mk("frame", x=-800, y=-800, w=600, h=500)
        inner = [mk("sticky", x=-700, y=-700), mk("text", x=-500, y=-600, text="x")]
        settle(0.1)
        press_delete([f])
        undo_redo()
        press_delete([f] + inner)
        undo_redo()

    @scenario
    def ink():
        d = mk("ink", x=0, y=-400, points=[[0, 0], [50, 30], [100, 10]])
        press_delete([d])
        undo_redo()

    @scenario
    def during_text_edit():
        s = mk("sticky", x=600, y=0, text="edit")
        settle(0.1)
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, vp(s))
        settle(0.2)
        log(f"  edition : {s.text_item is not None and s.text_item.editing()}")
        s.setSelected(True)
        scene.delete_items([s])            # commande d'effacement pendant l'edition
        settle(0.2)
        undo_redo()

    @scenario
    def under_mouse_click_then_delete():
        s = mk("sticky", x=600, y=400)
        settle(0.1)
        p = vp(s)
        QTest.mouseMove(view.viewport(), p)
        settle(0.05)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        settle(0.1)
        QTest.keyClick(view.viewport(), Qt.Key_Delete)
        settle(0.1)
        QTest.mouseMove(view.viewport(), p + QPoint(3, 3))
        settle(0.1)
        undo_redo()

    @scenario
    def press_hold_delete():
        s = mk("shape", x=900, y=400, w=150, h=150)
        settle(0.1)
        p = vp(s)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        settle(0.05)
        QTest.keyClick(view.viewport(), Qt.Key_Delete)    # element saisi par la souris
        settle(0.05)
        QTest.mouseMove(view.viewport(), p + QPoint(20, 20))
        settle(0.05)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, p + QPoint(20, 20))
        settle(0.1)
        undo_redo()

    @scenario
    def multi_all():
        for i in range(6):
            mk("sticky", x=1200 + i * 220, y=0)
        settle(0.1)
        QTest.keyClick(view.viewport(), Qt.Key_A, Qt.ControlModifier)
        settle(0.1)
        QTest.keyClick(view.viewport(), Qt.Key_Delete)
        settle(0.1)
        undo_redo(3)

    @scenario
    def more_menu_delete():
        s = mk("sticky", x=0, y=800)
        scene.clearSelection()
        s.setSelected(True)
        settle(0.1)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMenu

        def trigger():
            menu = APP.activePopupWidget()
            log(f"  menu : {menu}")
            if isinstance(menu, QMenu):
                for a in menu.actions():
                    if a.text().startswith("Supprimer"):
                        a.trigger()
                        menu.close()
                        return
        QTimer.singleShot(300, trigger)
        pane._open_more_menu(next(w for k, w in pane._miro_bars.manager.widgets.items() if k.endswith("more")
                                  or getattr(w, "palette_key", "") == "more"))
        settle(0.4)
        undo_redo()

    @scenario
    def cut():
        s = mk("sticky", x=300, y=800)
        press_delete([])
        s.setSelected(True)
        QTest.keyClick(view.viewport(), Qt.Key_X, Qt.ControlModifier)
        settle(0.1)
        QTest.keyClick(view.viewport(), Qt.Key_V, Qt.ControlModifier)
        settle(0.1)
        undo_redo()

    @scenario
    def repeat_fast():
        items = [mk(k, x=-1500 + n * 210, y=1200) for n, k in enumerate(["sticky", "text", "shape", "frame"] * 3)]
        for it in items:
            it.setSelected(True)
            QTest.keyClick(view.viewport(), Qt.Key_Delete)
            APP.processEvents()
        settle(0.2)
        for _ in range(12):
            scene.undo.undo()
            APP.processEvents()
        for _ in range(12):
            scene.undo.redo()
            APP.processEvents()
        settle(0.2)

    only = [a for a in sys.argv[1:] if a != "gpu"]
    for f in scenarios:
        if only and f.__name__ not in only:
            continue
        log(f"== {f.__name__} ({'GPU' if GPU else 'classique'})")
        f()
        settle(0.2)
    log("fin sans plantage")
    pane._autosave.stop()
    pane.deleteLater()
    settle(0.2)


if __name__ == "__main__":
    main()
