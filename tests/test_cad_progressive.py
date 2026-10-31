"""Ouverture d'un GROS board / dessin importe PAR TRANCHES (demande de l'utilisateur : « ca rame enormement » a
l'ouverture d'un DWG de 40 000 lignes, ~16 s d'interface figee) : `BoardScene.load_data(progressive=True)`, lignes
CAD regroupees en lots au fur et a mesure (`CadLayer.bulk_append`), jamais d'enregistrement tronque, passes
completes du ramasse-miettes rendues a la fin ; copie rapide des valeurs (`clone_data`)."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import copy
import gc
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

import app_style  # noqa: E402
import fm_board as board  # noqa: E402
from fm_board import model  # noqa: E402
from fm_board import scene as scene_mod  # noqa: E402
from fm_board import ui as board_ui  # noqa: E402
from fm_cad import cad_model  # noqa: E402
from fm_cad.cad_items import CadLineItem  # noqa: E402
from fm_miro.items import clone_data  # noqa: E402


def drawing(count: int, sticky_every: int = 0) -> dict:
    cad = cad_model.empty_cad_page()
    items = []
    for n in range(count):
        x, y = (n % 80) * 20.0, (n // 80) * 20.0
        items.append(model.new_item("cad_line", **cad_model.new_line_values(cad, (x, y), (x + 15.0, y + 9.0))))
        if sticky_every and n % sticky_every == sticky_every - 1:
            items.append(model.new_item("sticky", x=x, y=-y, text=f"note {n}"))
    data = model.empty_board()
    data["page"]["cad"] = cad
    data["items"] = items
    return model.normalize(data)


class ProgressiveLoadTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.host.show()
        self.pane = board_ui.BoardPane(self.host)
        self.assertTrue(self.pane.open(board.create_board_file(self.dir / "plan")))
        self.pane.show()
        self.addCleanup(self._drop)
        self.thresholds = gc.get_threshold()

    def _drop(self):
        try:
            self.pane._autosave.stop()
            self.pane.deleteLater()
            self.host.deleteLater()
        except RuntimeError:
            pass
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def wait_loaded(self, scene, limit=30.0):
        end = time.monotonic() + limit
        while scene.loading():
            APP.processEvents()
            self.assertLess(time.monotonic(), end, "chargement par tranches inacheve")

    def test_big_import_loads_by_slices_and_ends_batched(self):
        data = drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 1500)
        total = len(data["items"])
        scene = self.pane.scene
        progress = []
        scene.loadProgress.connect(lambda done, count: progress.append((done, count)))
        start = time.perf_counter()
        self.pane.open_import(data, self.dir / "plan.dwg", normalized=True)
        first = time.perf_counter() - start
        self.assertTrue(scene.loading())                                    # la suite vient par tranches
        self.assertLess(len(scene._items), total)
        self.assertLess(first, 0.5)                                         # l'interface rend la main tout de suite
        self.assertEqual(gc.get_threshold()[2], 1_000_000)                  # passes completes suspendues
        saved = scene.to_data()                                             # enregistrement pendant le chargement
        self.assertEqual(len(saved["items"]), total)                        # jamais tronque
        self.wait_loaded(scene)
        self.assertEqual(len(scene._items), total)
        self.assertEqual(progress[-1], (total, total))
        self.assertFalse(scene.bulk_loading)
        self.assertEqual(gc.get_threshold(), self.thresholds)               # rendues
        lines = [i for i in scene._items.values() if isinstance(i, CadLineItem)]
        self.assertTrue(all(line._batch is not None for line in lines))     # toutes peintes par un lot
        self.assertEqual(len(scene.cad_layer.batches), 1)                   # au fur et a mesure, dans l'ordre
        self.assertEqual(scene.cad_layer.batches[0].members, lines)
        self.assertFalse(scene.undo.canUndo())
        self.assertFalse(self.pane._dirty)                                  # charge = rien a enregistrer

    def test_mixed_board_is_regrouped_at_the_end(self):
        data = drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 500, sticky_every=700)
        scene = self.pane.scene
        scene.load_data(data, progressive=True)
        self.wait_loaded(scene)
        for _ in range(3):
            APP.processEvents()
        lines = [i for i in scene._items.values() if isinstance(i, CadLineItem)]
        self.assertEqual(len(scene._items), len(data["items"]))
        self.assertTrue(all(line._batch is not None for line in lines))
        self.assertGreater(len(scene.cad_layer.batches), 1)                 # coupes par les notes

    def test_small_board_and_default_stay_synchronous(self):
        scene = self.pane.scene
        scene.load_data(drawing(300), progressive=True)
        self.assertFalse(scene.loading())
        self.assertEqual(len(scene._items), 300)
        scene.load_data(drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 10))      # par defaut : tout de suite
        self.assertFalse(scene.loading())
        self.assertEqual(len(scene._items), scene_mod.LOAD_PROGRESSIVE_MIN + 10)

    def test_new_load_or_closed_scene_gives_gc_back(self):
        scene = self.pane.scene
        scene.load_data(drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 800), progressive=True)
        self.assertTrue(scene.loading())
        scene.load_data(drawing(10))                                        # remplace : l'ancien s'arrete
        self.assertFalse(scene.loading())
        self.assertEqual(gc.get_threshold(), self.thresholds)
        self.assertEqual(len(scene._items), 10)
        other = scene_mod.BoardScene()
        other.load_data(drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 800), progressive=True)
        self.assertEqual(gc.get_threshold()[2], 1_000_000)
        other.deleteLater()
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(gc.get_threshold(), self.thresholds)               # scene fermee avant la fin


class CloneDataTest(unittest.TestCase):
    def test_same_as_deepcopy_and_independent(self):
        data = {"id": "a", "p1": [1.0, 2.0], "vertices": [[0, 0, 0.5], [1, 1, 0]], "style": {"dash": [1, 2]},
                "none": None, "flag": True, "pair": (1, [2])}
        copied = clone_data(data)
        self.assertEqual(copied, copy.deepcopy(data))
        copied["vertices"][0][0] = 9
        copied["style"]["dash"].append(3)
        copied["pair"][1].append(5)
        self.assertEqual(data["vertices"][0][0], 0)
        self.assertEqual(data["style"]["dash"], [1, 2])
        self.assertEqual(data["pair"][1], [2])


if __name__ == "__main__":
    unittest.main()
