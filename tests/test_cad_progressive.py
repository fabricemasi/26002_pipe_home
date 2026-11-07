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
from unittest import mock
from pathlib import Path

from PySide6.QtWidgets import QApplication, QGraphicsItem, QWidget

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

    def test_hidden_and_locked_layers_apply_to_loaded_lines(self):
        """Proprietes, verrou et visibilite calcules a l'entree dans la scene, avec les VRAIS calques (plus a la
        creation de l'element, avec une page vide)."""
        data = drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 200)
        cad = data["page"]["cad"]
        cad["layers"].append({**cad_model.LAYER_DEFAULTS, "id": "cache", "name": "Cache", "visible": False})
        cad["layers"].append({**cad_model.LAYER_DEFAULTS, "id": "verrou", "name": "Verrou", "locked": True})
        for n, item in enumerate(data["items"]):
            item["layer"] = ("cache", "verrou", cad_model.LAYER0)[n % 3]
        scene = self.pane.scene
        scene.load_data(model.normalize(data), progressive=True)
        self.wait_loaded(scene)
        APP.processEvents()
        lines = [i for i in scene._items.values() if isinstance(i, CadLineItem)]
        by_layer = {key: [line for line in lines if line.data["layer"] == key]
                    for key in ("cache", "verrou", cad_model.LAYER0)}
        self.assertTrue(by_layer["cache"] and not any(line.isVisible() for line in by_layer["cache"]))
        self.assertTrue(all(line.isVisible() and line.locked() and not line.flags() & QGraphicsItem.ItemIsMovable
                            for line in by_layer["verrou"]))
        self.assertTrue(all(line.isVisible() and line.flags() & QGraphicsItem.ItemIsMovable for line in by_layer["0"]))

    def test_loading_shares_properties_and_never_reclassifies_after_qt_polish(self):
        """Gros dessin : proprietes effectives calculees une fois par style (`resolve_shared`), et les
        notifications de visibilite que Qt envoie a chaque element ajoute (« polish », visibilite inchangee) ne
        reclassent plus les lignes dans leur lot."""
        from unittest import mock
        from fm_cad import cad_items
        data = drawing(scene_mod.LOAD_PROGRESSIVE_MIN + 1000)
        resolves, changed = [], []
        real_resolve, real_changed = cad_model.resolve, cad_items.CadBatch.member_changed
        with mock.patch.object(cad_model, "resolve", lambda *a, **k: resolves.append(1) or real_resolve(*a, **k)), \
                mock.patch.object(cad_items.CadBatch, "member_changed",
                                  lambda self, *a: changed.append(1) or real_changed(self, *a)):
            scene = self.pane.scene
            scene.load_data(data, progressive=True)
            self.wait_loaded(scene)
            for _ in range(3):
                APP.processEvents()
        self.assertEqual(len(scene._items), len(data["items"]))
        self.assertLess(len(resolves), 10)                                  # 1 style ici (+ calques de la page)
        self.assertEqual(changed, [])

    def test_snap_index_of_a_big_drawing_is_built_in_background_slices(self):
        """Gros dessin : l'index des accrochages se construit EN FOND des la fin du chargement, par tranches courtes
        (plus de figement d'~1 s au 1er mouvement de souris) ; les entites supprimees / ajoutees pendant ce temps sont
        reprises a la fin."""
        from fm_cad import cad as cad_mod
        self.pane.toggle_cad(True)
        ctl = self.pane.cad
        data = drawing(cad_mod.BACKGROUND_INDEX_MIN + 500)
        scene = self.pane.scene
        steps = []
        real_step = cad_mod.CadController._index_step

        def timed(controller):
            t = time.perf_counter()
            real_step(controller)
            steps.append(time.perf_counter() - t)
        with mock.patch.object(cad_mod.CadController, "_index_step", timed):
            scene.load_data(data, progressive=True)
            self.wait_loaded(scene)
            APP.processEvents()
            self.assertIsNotNone(ctl._index_job)                            # lance a la fin du chargement
            t = time.perf_counter()
            ctl._source((-1.0, -10.0, 16.0, 1.0))                           # 1er mouvement : rien n'attend
            self.assertLess(time.perf_counter() - t, 0.2)
            lines = [i for i in scene._items.values() if isinstance(i, CadLineItem)]
            gone = lines[0]
            scene._remove(gone.item_id)
            cad = scene.page["cad"]
            added = scene._add(model.new_item("cad_line", **cad_model.new_line_values(cad, (5000.0, 5000.0),
                                                                                       (5040.0, 5000.0))))
            end = time.monotonic() + 30
            while ctl._index_job is not None:
                APP.processEvents()
                self.assertLess(time.monotonic(), end, "index jamais fini")
        self.assertGreater(len(steps), 3)                                    # vraiment par tranches
        self.assertLess(max(steps), 0.15)
        self.assertEqual(gc.get_threshold(), self.thresholds)               # ramasse-miettes rendu
        self.assertIn(lines[1], ctl._source((19.0, -1.0, 36.0, 10.0)))                 # ligne (20, 0)-(35, 9)
        self.assertIn(added, ctl._source((5010.0, 4990.0, 5020.0, 5010.0)))
        self.assertNotIn(gone, ctl._index.objects.values())

    def test_line_added_outside_loading_paints_itself_until_batched(self):
        """Creee sans contenu peint (`ITEM_FLAGS`) : hors chargement et sans GPU, elle se peint seule tout de suite,
        puis son lot la reprend a la boucle suivante."""
        scene = self.pane.scene
        scene.load_data(drawing(5))
        APP.processEvents()
        cad = scene.page["cad"]
        line = scene._add(model.new_item("cad_line", **cad_model.new_line_values(cad, (0.0, 0.0), (50.0, 0.0))))
        self.assertFalse(line.flags() & QGraphicsItem.ItemHasNoContents)
        self.assertIsNone(line._batch)
        for _ in range(3):
            APP.processEvents()
        self.assertIsNotNone(line._batch)
        self.assertTrue(line.flags() & QGraphicsItem.ItemHasNoContents)               # peinte par son lot


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
