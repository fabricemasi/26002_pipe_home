"""Sonde ALEATOIRE des plantages a l'effacement (board Miro), en vraie fenetre Windows :

    QT_QPA_PLATFORM=windows QT_QPA_FONTDIR=C:\\Windows\\Fonts .venv/Scripts/python.exe -X faulthandler tests/_probe_board_delete_stress.py [graine] [tours] [gpu]

Chaque action est ecrite avant d'etre jouee (la derniere ligne avant un plantage nomme le coupable)."""
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])
import app_style  # noqa: E402
import fm_board as board  # noqa: E402
from fm_board import model, serialization  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402

args = [a for a in sys.argv[1:] if a != "gpu"]
SEED = int(args[0]) if args else 1
TURNS = int(args[1]) if len(args) > 1 else 300
GPU = "gpu" in sys.argv[1:]


def settle(seconds=0.02):
    end = time.perf_counter() + seconds
    while True:
        APP.processEvents()
        if time.perf_counter() >= end:
            break
        time.sleep(0.002)


def main():
    rnd = random.Random(SEED)
    app_style.apply_style(APP)
    folder = Path(tempfile.mkdtemp())
    path = board.create_board_file(folder / "b")
    host = QWidget()
    host.resize(1300, 860)
    host.move(100, 60)
    host.show()
    settings = {}
    if os.environ.get("USER_SETTINGS"):           # reglages de l'utilisateur (copie isolee, _isolate)
        import settings_store
        import pipeline_browser as pb
        settings = settings_store.load_settings(startup=True)
        pb.apply_all_settings(settings)
        app_style.apply_style(APP)
        print("reglages de l'utilisateur, opengl =", settings.get("board_opengl"), flush=True)
    if GPU:
        settings["board_opengl"] = True
    pane = board_ui.BoardPane(host, settings)
    pane.stateChanged.connect(lambda: None)
    pane.set_module("miro")
    pane.open(path)
    pane.resize(1300, 860)
    pane.show()
    settle(0.4)
    scene, view = pane.scene, pane.view
    if GPU:
        view.set_gpu(True)
    img = folder / "i.png"
    q = QImage(300, 200, QImage.Format_RGB32)
    q.fill(QColor("teal"))
    q.save(str(img))
    asset = None
    if hasattr(serialization, "import_asset"):
        try:
            asset = serialization.import_asset(path, img)
        except Exception as error:      # noqa: BLE001
            print("asset", error)
    vp = view.viewport()

    def items():
        return [i for i in scene.board_items() if i.scene() is scene]

    def pt(item):
        return view.mapFromScene(item.scene_rect().center())

    def create():
        kind = rnd.choice(["sticky", "text", "shape", "frame", "ink", "connector", "image", "comment"])
        x, y = rnd.uniform(-500, 500), rnd.uniform(-350, 350)
        if kind == "ink":
            data = model.new_item("ink", x=x, y=y, points=[[0, 0], [40, 20], [80, 5]])
        elif kind == "connector":
            others = [i for i in items() if i.kind not in ("connector", "comment")]
            if len(others) < 2:
                return
            a, b = rnd.sample(others, 2)
            data = model.new_item("connector", start={"item": a.item_id}, end={"item": b.item_id})
        elif kind == "image":
            if not asset:
                return
            data = model.new_item("image", x=x, y=y, w=150, h=100, asset=asset)
        elif kind == "comment":
            others = [i for i in items() if i.kind != "comment"]
            if not others:
                return
            t = rnd.choice(others)
            data = model.new_item("comment", x=x, y=y, target=t.item_id)
        elif kind == "frame":
            data = model.new_item("frame", x=x, y=y, w=300, h=250)
        else:
            data = model.new_item(kind, x=x, y=y, text="ab")
        scene.add_new(data, select=rnd.random() < 0.5)
        scene.refresh_links()

    def select_some():
        pool = items()
        scene.clearSelection()
        for i in rnd.sample(pool, min(len(pool), rnd.randint(1, 4))):
            i.setSelected(True)

    def key_delete():
        view.setFocus()
        QTest.keyClick(vp, rnd.choice([Qt.Key_Delete, Qt.Key_Backspace]))

    def click_delete():
        pool = items()
        if not pool:
            return
        p = pt(rnd.choice(pool))
        QTest.mouseMove(vp, p)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p)
        QTest.keyClick(vp, Qt.Key_Delete)
        QTest.mouseMove(vp, p + QPoint(2, 2))

    def drag_delete():
        pool = items()
        if not pool:
            return
        p = pt(rnd.choice(pool))
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p)
        QTest.mouseMove(vp, p + QPoint(15, 10))
        QTest.keyClick(vp, Qt.Key_Delete)
        QTest.mouseMove(vp, p + QPoint(30, 20))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p + QPoint(30, 20))

    def edit_then_delete():
        pool = [i for i in items() if i.text_item is not None]
        if not pool:
            return
        it = rnd.choice(pool)
        QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, pt(it))
        settle()
        QTest.keyClicks(vp, "xy")
        if rnd.random() < 0.5:
            scene.delete_items([it])
        else:
            QTest.keyClick(vp, Qt.Key_Escape)
            QTest.keyClick(vp, Qt.Key_Delete)

    def undo():
        scene.undo.undo()

    def redo():
        scene.undo.redo()

    def cut_paste():
        QTest.keyClick(vp, Qt.Key_X, Qt.ControlModifier)
        if rnd.random() < 0.7:
            QTest.keyClick(vp, Qt.Key_V, Qt.ControlModifier)

    def select_all_delete():
        QTest.keyClick(vp, Qt.Key_A, Qt.ControlModifier)
        QTest.keyClick(vp, Qt.Key_Delete)

    def zoom():
        view.set_zoom(rnd.choice([0.1, 0.13, 0.2, 0.35, 0.5, 0.8, 1.0, 1.7, 2.5, 4.0]))

    actions = [(zoom, 4), (create, 6), (select_some, 4), (key_delete, 4), (click_delete, 3), (drag_delete, 2),
               (edit_then_delete, 2), (undo, 4), (redo, 3), (cut_paste, 1), (select_all_delete, 0.3)]
    names = [a for a, _w in actions]
    weights = [w for _a, w in actions]
    for turn in range(TURNS):
        action = rnd.choices(names, weights)[0]
        print(f"{turn} {action.__name__} n={len(items())} sel={len(scene.selectedItems())}", flush=True)
        action()
        settle(rnd.choice([0.0, 0.0, 0.01, 0.05]))
    print("fin sans plantage", flush=True)
    pane._autosave.stop()


if __name__ == "__main__":
    main()
