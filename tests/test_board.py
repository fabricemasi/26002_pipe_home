"""Module « Board » (paquet board/, facon Miro) : fichier .mro (compatibilite, elements inconnus gardes), images
(cycle de vie sur), scene (annulation, connecteurs, copier / coller, magnetisme), grille et ombre comme Miro,
dessin a main levee, formes, commentaires, reglages (MRO et page), echanges JSON avec l'API Miro, export, et le
mode board de la fenetre principale."""
import os as _os, sys as _sys  # jamais les vrais reglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

APP = QApplication.instance() or QApplication([])

import app_style
import fm_board as board
from fm_board import export, model, serialization
from fm_miro import miro_io, smart
from fm_board.scene import PAGE, BoardScene, grid_alpha
from fm_board import ui as board_ui

_PANES = []


class BoardPane(board_ui.BoardPane):
    """Panneau retenu pour etre detruit a la fin du test (sinon son enregistrement automatique part plus tard,
    dans un dossier de test deja supprime)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _PANES.append(self)


def drop_panes():
    from PySide6.QtCore import QCoreApplication, QEvent
    for pane in _PANES:
        try:
            pane._autosave.stop()
            pane.deleteLater()
        except RuntimeError:
            pass
    _PANES.clear()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def settle(seconds=0.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.005)


def make_image(path, color="red", size=10):
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor(color))
    img.save(str(path))
    return path


class ModelTest(unittest.TestCase):
    def test_unknown_items_and_keys_are_kept(self):
        data = model.normalize({"version": 7, "future": {"a": 1},
                                "items": [{"type": "sticky", "id": "a", "text": "x", "glow": 3}, {"type": "alien", "id": "z"},
                                          {"type": "sticky", "id": "a"}], "view": {"zoom": 99}})
        self.assertEqual([i["type"] for i in data["items"]], ["sticky", "sticky"])
        self.assertEqual(data["items"][0]["glow"], 3)                       # champ inconnu garde
        self.assertEqual(data["foreign"], [{"type": "alien", "id": "z"}])  # element inconnu garde a part
        self.assertNotEqual(data["items"][0]["id"], data["items"][1]["id"])
        self.assertEqual(data["view"]["zoom"], 99.0)                     # jamais borne a la lecture
        scene = BoardScene()
        scene.load_data(data)
        out = scene.to_data()
        self.assertEqual(out["future"], {"a": 1})
        self.assertEqual(out["version"], 7)
        self.assertIn({"type": "alien", "id": "z"}, out["items"])

    def test_version_1_files_open_with_their_look(self):
        old = {"format": "pipeline-board", "version": 1, "view": {"zoom": 1.0, "center": [0, 0]},
               "items": [{"id": "s", "type": "shape", "shape": "round", "w": 200, "h": 100, "x": 0, "y": 0, "z": 1,
                          "fill": "#2d9bf0", "fill_opacity": 0.0, "stroke": "#e6e6e6", "stroke_width": 2,
                          "text": "a", "font_size": 18, "text_color": "#e6e6e6"},
                         {"id": "t", "type": "sticky", "w": 200, "h": 200, "x": 0, "y": 0, "z": 2,
                          "color": "#fff9b1", "text": "b", "font_size": 20, "text_color": "#1a1a1a"}]}
        data = model.normalize(old)
        shape, sticky = data["items"]
        self.assertEqual(shape["radius"], 18.0)                           # 18 % du plus petit cote
        self.assertEqual(shape["stroke"], "#e6e6e6")                      # couleurs du fichier gardees
        self.assertEqual(sticky["font_size"], 20)
        self.assertEqual(data["page"]["background"], None)                # fond Miro par defaut


class SerializationTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)

    def test_create_load_save_round_trip(self):
        path = board.create_board_file(self.dir / "plan")
        self.assertEqual(path.name, "plan.mro")
        with self.assertRaises(FileExistsError):
            board.create_board_file(path)
        data = serialization.load(path)
        data["items"].append(model.new_item("sticky", text="é"))
        serialization.save(path, data)
        self.assertEqual(serialization.load(path)["items"][0]["text"], "é")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format"], "pipeline-board")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["plan.mro"])

    def test_invalid_file_raises_board_error(self):
        path = self.dir / "x.mro"
        path.write_text("{pas du json", encoding="utf-8")
        with self.assertRaises(serialization.BoardError):
            serialization.load(path)

    def test_images_are_copied_once_and_originals_never_touched(self):
        path = board.create_board_file(self.dir / "b")
        image = make_image(self.dir / "photo.png")
        a = serialization.import_asset(path, image)
        b = serialization.import_asset(path, image)
        self.assertEqual(a, b)
        self.assertTrue(serialization.asset_path(path, a).is_file())
        self.assertEqual(serialization.assets_dir(path).name, "b_assets")
        serialization.cleanup_assets(path, set())
        self.assertTrue(image.is_file())                                  # l'original reste
        self.assertFalse(serialization.asset_path(path, a).exists())

    def test_cleanup_never_touches_foreign_files(self):
        path = board.create_board_file(self.dir / "b")
        folder = serialization.assets_dir(path)
        folder.mkdir()
        (folder / "mes_notes.txt").write_text("a moi", encoding="utf-8")
        (folder / "sub").mkdir()
        (folder / "sub" / "0123456789abcdef.png").write_bytes(b"x")
        other = board.create_board_file(self.dir / "autre")
        mine = serialization.import_asset(other, make_image(self.dir / "p.png"))
        serialization.cleanup_assets(path, set())
        self.assertTrue((folder / "mes_notes.txt").is_file())
        self.assertTrue((folder / "sub" / "0123456789abcdef.png").is_file())
        self.assertTrue(serialization.asset_path(other, mine).is_file())   # un autre board : jamais touche

    def test_orphans_are_swept_only_when_older_than_the_board(self):
        path = board.create_board_file(self.dir / "b")
        old = serialization.import_asset(path, make_image(self.dir / "a.png", "red"))
        new = serialization.import_asset(path, make_image(self.dir / "c.png", "blue"))
        past = time.time() - 3600
        os.utime(serialization.asset_path(path, old), (past, past))
        removed = serialization.cleanup_assets(path, set(), min_age_s=serialization.ORPHAN_AGE_S,
                                               older_than=time.time() - 60)
        self.assertEqual(removed, [old])
        self.assertTrue(serialization.asset_path(path, new).is_file())


class AssetLifecycleTest(unittest.TestCase):
    """Images d'un board : retirees du dossier seulement quand plus rien ne peut les montrer."""

    def setUp(self):
        app_style.apply_style(APP)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)
        self.path = board.create_board_file(self.dir / "b")
        self.host = QWidget()
        self.host.resize(900, 600)
        self.addCleanup(self.host.deleteLater)
        self.pane = BoardPane(self.host)
        self.assertTrue(self.pane.open(self.path))
        self.name = serialization.import_asset(self.path, make_image(self.dir / "photo.png"))
        self.file = serialization.asset_path(self.path, self.name)

    def _image(self, **kw):
        return self.pane.scene.add_new(model.new_item("image", asset=self.name, **kw))

    def test_deleted_image_stays_while_undo_can_bring_it_back(self):
        pane, scene = self.pane, self.pane.scene
        image = self._image()
        self.assertTrue(pane.save())
        scene.delete_items([image])
        self.assertTrue(pane.save())                                      # sauvegarde automatique
        self.assertTrue(self.file.is_file())                             # encore accessible par Ctrl+Z
        scene.undo.undo()
        self.assertIsNotNone(scene.item(image.item_id))
        self.assertTrue(pane.save())
        scene.undo.redo()
        self.assertTrue(pane.save())
        self.assertTrue(self.file.is_file())
        self.assertTrue(pane.confirm_leave())                             # fermeture : la pile disparait
        self.assertFalse(self.file.exists())

    def test_shared_image_is_kept_until_its_last_use(self):
        pane, scene = self.pane, self.pane.scene
        first, second = self._image(), self._image(x=400)
        scene.delete_items([first])
        self.assertTrue(pane.confirm_leave())
        self.assertTrue(self.file.is_file())                             # l'autre copie l'utilise encore
        pane2 = BoardPane(self.host)
        self.assertTrue(pane2.open(self.path))
        pane2.scene.delete_items([pane2.scene.item(second.item_id)])
        self.assertTrue(pane2.confirm_leave())
        self.assertFalse(self.file.exists())

    def test_failed_save_or_conflict_removes_nothing(self):
        pane, scene = self.pane, self.pane.scene
        image = self._image()
        self.assertTrue(pane.save())
        scene.delete_items([image])
        scene.undo.clear()
        scene.commands.clear()
        with mock.patch.object(serialization, "save", side_effect=OSError("disque plein")), \
                mock.patch.object(QMessageBox, "warning"):
            self.assertFalse(pane.save())
        self.assertTrue(self.file.is_file())
        os.utime(self.path, ns=(time.time_ns() + 5_000_000_000,) * 2)      # modifie ailleurs
        with mock.patch.object(QMessageBox, "exec", return_value=0), \
                mock.patch.object(QMessageBox, "clickedButton", return_value=None):
            self.assertFalse(pane.save())                                  # Annuler
        self.assertTrue(self.file.is_file())

    def test_cancelled_import_is_swept_at_close(self):
        orphan = serialization.import_asset(self.path, make_image(self.dir / "x.png", "green"))
        self.assertTrue(self.pane.confirm_leave())
        self.assertFalse(serialization.asset_path(self.path, orphan).exists())

    def test_paste_from_another_board_copies_the_image(self):
        other = board.create_board_file(self.dir / "autre")
        name = serialization.import_asset(other, make_image(self.dir / "o.png", "blue"))
        serialization.cleanup_assets(self.path, set())                    # rien dans ce board
        dicts = [model.new_item("image", asset=name)]
        self.pane.scene.paste(dicts, QPointF(0, 0), source_board=other)
        self.assertTrue(serialization.asset_path(self.path, name).is_file())
        self.assertTrue(serialization.asset_path(other, name).is_file())


class SceneTest(unittest.TestCase):
    def setUp(self):
        self.scene = BoardScene()

    def test_add_change_delete_are_undoable(self):
        scene = self.scene
        note = scene.add_new(model.new_item("sticky", text="a"))
        scene.change_items([note], lambda i: i.data.update(color="#2d9bf0"), "Couleur")
        self.assertEqual(scene.item(note.item_id).data["color"], "#2d9bf0")
        scene.undo.undo()
        self.assertEqual(scene.item(note.item_id).data["color"], model.MIRO_STICKY)
        scene.delete_items([scene.item(note.item_id)])
        self.assertIsNone(scene.item(note.item_id))
        scene.undo.undo()
        self.assertEqual(scene.item(note.item_id).data["text"], "a")
        scene.undo.undo()
        self.assertEqual(scene.board_items(), [])
        scene.undo.redo()
        self.assertIsNotNone(scene.item(note.item_id))

    def test_live_change_is_one_undo_step(self):
        scene = self.scene
        shape = scene.add_new(model.new_item("shape", w=100, h=60))
        count = scene.undo.count()
        for value in (5, 10, 20, 40):
            scene.live_change("radius", [shape], lambda i, v=value: i.data.update(radius=float(v)), "Arrondi")
        scene.commit_live()
        self.assertEqual(scene.undo.count(), count + 1)
        self.assertEqual(scene.item(shape.item_id).data["radius"], 40.0)
        scene.undo.undo()
        self.assertEqual(scene.item(shape.item_id).data["radius"], 0.0)

    def test_connector_follows_its_items_and_goes_with_them(self):
        scene = self.scene
        a = scene.add_new(model.new_item("shape", x=0, y=0, w=100, h=100))
        b = scene.add_new(model.new_item("shape", x=400, y=0, w=100, h=100))
        arrow = scene.add_new(model.new_item("connector", src={"item": a.item_id}, dst={"item": b.item_id}))
        self.assertAlmostEqual(arrow._line.p1().x(), 100)
        self.assertAlmostEqual(arrow._line.p2().x(), 400)
        b.setPos(0, 400)
        self.assertEqual((arrow._line.p2().x(), arrow._line.p2().y()), (50, 400))
        scene.delete_items([a])
        self.assertIsNone(scene.item(arrow.item_id))
        scene.undo.undo()
        self.assertIsNotNone(scene.item(arrow.item_id))

    def test_paste_gives_new_ids_and_keeps_links(self):
        scene = self.scene
        a = scene.add_new(model.new_item("sticky"))
        b = scene.add_new(model.new_item("sticky", x=300))
        scene.add_new(model.new_item("connector", src={"item": a.item_id}, dst={"item": b.item_id}))
        pasted = scene.paste(scene.serialize(scene.board_items()), QPointF(50, 50))
        self.assertEqual(len(pasted), 3)
        arrow = next(i for i in pasted if i.kind == "connector")
        self.assertTrue(arrow.attached_ids() <= {i.item_id for i in pasted})

    def test_locked_items_do_not_move_change_or_delete(self):
        scene = self.scene
        note = scene.add_new(model.new_item("sticky"))
        scene.change_items([note], lambda i: i.data.update(locked=True), "Verrouiller", include_locked=True)
        note = scene.item(note.item_id)
        from PySide6.QtWidgets import QGraphicsItem
        self.assertFalse(note.flags() & QGraphicsItem.ItemIsMovable)
        scene.change_items([note], lambda i: i.data.update(color="#000000"), "Couleur")
        self.assertEqual(note.data["color"], model.MIRO_STICKY)
        scene.delete_items([note])
        self.assertIsNotNone(scene.item(note.item_id))

    def test_rotation_and_order_are_saved(self):
        scene = self.scene
        a = scene.add_new(model.new_item("shape", rotation=30.0))
        b = scene.add_new(model.new_item("shape"))
        self.assertEqual(a.rotation(), 30.0)
        scene.bring_to_front([a])
        self.assertGreater(scene.item(a.item_id).zValue(), b.zValue())
        scene.step_z([scene.item(a.item_id)], -1)
        self.assertLess(scene.item(a.item_id).zValue(), b.zValue())
        data = {d["id"]: d for d in scene.to_data()["items"]}
        self.assertEqual(data[a.item_id]["rotation"], 30.0)


class SnapTest(unittest.TestCase):
    def setUp(self):
        self.scene = BoardScene()
        self.scene.visible_rect = QRectF(-2000, -2000, 4000, 4000)
        self.other = self.scene.add_new(model.new_item("shape", x=0, y=0, w=100, h=100))
        self.moving = self.scene.add_new(model.new_item("shape", x=203, y=150, w=100, h=100))
        self.scene.clearSelection()
        self.moving.setSelected(True)
        self.scene._move_before = self.scene.snapshot([self.moving.item_id])

    def test_snaps_to_object_edges_within_screen_distance(self):
        self.moving.setPos(103, 150)                                      # bord gauche a 3 px du bord droit
        self.scene._snap_move()
        self.assertEqual(self.moving.pos().x(), 100)
        self.assertTrue(self.scene.guides)

    def test_distance_follows_the_zoom_and_settings(self):
        self.scene.set_zoom(0.25)                                          # 3 unites = 0,75 px : aimante
        self.moving.setPos(130, 150)                                      # 30 unites = 7,5 px : au-dela de 6
        self.scene._snap_move()
        self.assertEqual(self.moving.pos().x(), 130)
        self.scene.snap["distance"] = 10
        self.scene._snap_move()
        self.assertEqual(self.moving.pos().x(), 100)

    def test_grid_snap_and_disabled_objects(self):
        self.scene.snap.update(objects=False, grid=True)
        step = self.scene.grid_step()
        self.moving.setPos(step * 10 + 2, step * 3 + 1)
        self.scene._snap_move()
        self.assertEqual((self.moving.pos().x(), self.moving.pos().y()), (step * 10, step * 3))

    def test_alt_or_switch_disables_snap(self):
        self.assertFalse(self.scene.snap_active(Qt.AltModifier))
        self.scene.snap["enabled"] = False
        self.assertFalse(self.scene.snap_active(Qt.NoModifier))


class LookTest(unittest.TestCase):
    """Grille et ombre comme Miro (valeurs mesurees sur les captures de l'utilisateur)."""

    def _grid_row(self, zoom):
        scene = BoardScene()
        img = QImage(400, 40, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        transform = QTransform.fromScale(zoom, zoom)
        transform.translate(3.3, 0)
        painter.setWorldTransform(transform)
        scene.drawBackground(painter, QRectF(-3.3, 0, 400 / zoom, 40 / zoom))
        painter.end()
        return [QColor(img.pixel(x, 20)).red() for x in range(400)]

    def test_grid_colors_and_levels_match_the_captures(self):
        self.assertEqual(grid_alpha(10), 0.0)
        self.assertAlmostEqual(grid_alpha(36), 0.5)
        self.assertEqual(grid_alpha(80), 1.0)
        row = self._grid_row(0.5625)                                       # niveau fin a 36 px a l'ecran
        lines = [(x, v) for x, v in enumerate(row) if v < 242]
        self.assertEqual({v for _x, v in lines}, {234, 227})              # #eaeaea et ~#e2e2e2 (capture 1)
        gaps = {b[0] - a[0] for a, b in zip(lines, lines[1:])}
        self.assertEqual(gaps, {36})
        self.assertIn(242, row)                                            # fond #f2f2f2

    def test_grid_changes_continuously_with_the_zoom(self):
        darkness = []
        for zoom in (0.5, 0.52, 0.54, 0.56, 0.58, 0.6):
            row = self._grid_row(zoom)
            darkness.append(sum(242 - v for v in row))
        steps = [abs(b - a) for a, b in zip(darkness, darkness[1:])]
        self.assertLess(max(steps), 0.35 * max(darkness))                 # pas de saut d'un cran a l'autre

    def test_sticky_shadow_is_below_and_soft(self):
        from fm_miro.items import StickyItem
        note = StickyItem(model.new_item("sticky", w=318, h=330))
        self.assertGreater(note.boundingRect().bottom(), 330 + 20)        # place de l'ombre comprise
        img = QImage(460, 460, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(model.MIRO_BACKGROUND))
        painter = QPainter(img)
        painter.translate(45, 27)
        note.paint_content(painter)
        painter.end()
        below = [242 - QColor(img.pixel(200, 356 + dy)).red() for dy in (1, 5, 10, 16, 24)]
        self.assertTrue(18 <= below[0] <= 28, below)                     # capture 2 : 23
        self.assertEqual(below, sorted(below, reverse=True))              # decroit
        self.assertEqual(242 - QColor(img.pixel(200, 20)).red(), 0)        # rien au-dessus


class DrawingTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.host = QWidget()
        self.host.resize(1000, 700)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)
        self.path = board.create_board_file(self.dir / "b")
        self.pane = BoardPane(self.host)
        self.pane.open(self.path)
        self.pane.fit()
        self.pane.show()
        self.view = self.pane.view
        settle(0.05)

    def stroke(self, points, tool):
        from PySide6.QtTest import QTest
        self.view.set_tool(tool)
        viewport = self.view.viewport()
        first = self.view.mapFromScene(QPointF(*points[0]))
        QTest.mousePress(viewport, Qt.LeftButton, pos=first)
        for x, y in points[1:]:
            QTest.mouseMove(viewport, self.view.mapFromScene(QPointF(x, y)))
        QTest.mouseRelease(viewport, Qt.LeftButton, pos=self.view.mapFromScene(QPointF(*points[-1])))

    def test_pen_and_highlighter_strokes_are_saved(self):
        self.pane._choose_draw_tool("highlighter")
        self.stroke([(0, 0), (40, 10), (80, 0)], "highlighter")
        self.pane._choose_draw_tool("pen")
        self.pane._preset_index["pen"] = 2
        self.pane._apply_preset()
        self.stroke([(0, 100), (40, 110), (80, 100)], "pen")
        self.assertTrue(self.pane.save())
        inks = [i for i in serialization.load(self.path)["items"] if i["type"] == "ink"]
        tools = sorted((i["tool"], i["width"], i["color"]) for i in inks)
        self.assertEqual(tools, [("highlighter", 16.0, "#fac710"), ("pen", 8.0, "#62c167")])

    def test_smart_drawing_turns_strokes_into_shapes(self):
        square = [(0, 0), (100, 0), (100, 100), (0, 100), (0, 3)]
        dense = []
        for (x0, y0), (x1, y1) in zip(square, square[1:]):
            dense += [(x0 + (x1 - x0) * t / 10, y0 + (y1 - y0) * t / 10) for t in range(10)]
        self.stroke(dense + [(1, 2)], "smart")
        self.stroke([(0, 300), (50, 302), (100, 300), (150, 301)], "smart")
        kinds = sorted((i.kind, i.data.get("shape")) for i in self.pane.scene.board_items())
        self.assertEqual(kinds, [("connector", None), ("shape", "rect")])

    def test_erasers(self):
        self.stroke([(0, 0), (100, 0), (200, 0)], "pen")
        self.stroke([(0, 100), (100, 100), (200, 100)], "pen")
        self.stroke([(100, -20), (100, 20)], "precision_eraser")         # coupe le 1er trait en deux
        inks = [i for i in self.pane.scene.board_items() if i.kind == "ink"]
        self.assertEqual(len(inks), 3)
        self.pane.scene.undo.undo()
        self.assertEqual(len([i for i in self.pane.scene.board_items() if i.kind == "ink"]), 2)
        self.stroke([(100, 90), (100, 110)], "eraser")                    # efface le 2e trait entier
        self.assertEqual(len([i for i in self.pane.scene.board_items() if i.kind == "ink"]), 1)

    def test_lasso_selects_what_it_surrounds(self):
        inside = self.pane.scene.add_new(model.new_item("sticky", x=0, y=0, w=50, h=50), select=False)
        outside = self.pane.scene.add_new(model.new_item("sticky", x=400, y=0, w=50, h=50), select=False)
        self.stroke([(-20, -20), (80, -20), (80, 80), (-20, 80), (-20, -15)], "lasso")
        self.assertTrue(inside.isSelected())
        self.assertFalse(outside.isSelected())

    def test_recognizer(self):
        circle = [QPointF(50 + 50 * __import__("math").cos(t / 20 * 6.283), 50 + 50 * __import__("math").sin(t / 20 * 6.283))
                  for t in range(21)]
        self.assertEqual(smart.recognize(circle)[0], "ellipse")
        self.assertIsNone(smart.recognize([QPointF(0, 0), QPointF(50, 80), QPointF(100, 0), QPointF(150, 80)]))


class ShapeAndCommentTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)
        self.path = board.create_board_file(self.dir / "b")
        self.pane = BoardPane(self.host)
        self.pane.open(self.path)
        self.pane.fit()
        self.pane.show()
        self.scene = self.pane.scene
        settle(0.05)

    def test_every_shape_paints_and_radius_is_bounded(self):
        for kind in model.SHAPE_KINDS:
            self.scene.add_new(model.new_item("shape", shape=kind, w=120, h=80, radius=500.0))
        self.pane.view.viewport().grab()
        from fm_miro.items import max_radius, shape_path
        path = shape_path("rect", QRectF(0, 0, 120, 80), 500)
        self.assertTrue(path.boundingRect().width() <= 120.01)
        self.assertEqual(max_radius(120, 80), 40)

    def test_context_bar_offers_the_shape_commands(self):
        shape = self.scene.add_new(model.new_item("shape"))
        settle(0.05)
        tips = {self.pane._context_layout.itemAt(i).widget().toolTip()
                for i in range(self.pane._context_layout.count())}
        for tip in ("Forme", "Police", "Taille du texte", "Lien", "Fond (couleur, opacité)",
                    "Contour (couleur, épaisseur, style, opacité, arrondi)", "Verrouiller (Ctrl+Maj+L)", "Plus…"):
            self.assertIn(tip, tips)
        self.pane._set_shape_kind("hexagon")
        self.assertEqual(self.scene.item(shape.item_id).data["shape"], "hexagon")
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(shape.item_id).data["shape"], "rect")

    def test_multi_selection_changes_every_item_that_has_the_property(self):
        a = self.scene.add_new(model.new_item("shape"))
        b = self.scene.add_new(model.new_item("sticky"), select=False)
        a.setSelected(True)
        b.setSelected(True)
        self.pane._change(self.pane._targets(("sticky", "shape", "frame")),
                          lambda i: i.data.update({"color" if i.kind == "sticky" else "fill": "#ff0000"}), "Fond")
        self.assertEqual(self.scene.item(a.item_id).data["fill"], "#ff0000")
        self.assertEqual(self.scene.item(b.item_id).data["color"], "#ff0000")
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(b.item_id).data["color"], model.MIRO_STICKY)

    def test_comment_thread_is_saved_and_undoable(self):
        panel = self.pane._comment_panel
        target = self.scene.add_new(model.new_item("shape", x=0, y=0))
        self.pane._comment_on(target)
        comment = panel.comment
        count = self.scene.undo.count()
        panel._input.setPlainText("Première remarque")
        panel._submit()
        panel._input.setPlainText("Réponse")
        panel._submit()
        self.assertEqual(self.scene.undo.count(), count + 2)
        self.assertEqual([m["text"] for m in comment.data["messages"]], ["Première remarque", "Réponse"])
        panel._toggle_resolved()
        self.assertFalse(self.scene.item(comment.item_id).isVisible())   # resolu : cache
        self.scene.set_page({"show_resolved": True})
        self.assertTrue(self.scene.item(comment.item_id).isVisible())
        target.setPos(500, 300)
        self.assertEqual(self.scene.item(comment.item_id).pos().x(), 500 + target.data["w"])   # il suit
        self.scene.delete_items([target])
        self.assertEqual(self.scene.item(comment.item_id).data["target"], "")   # detache, reste
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(comment.item_id).data["target"], target.item_id)
        self.assertTrue(self.pane.save())
        saved = [i for i in serialization.load(self.path)["items"] if i["type"] == "comment"][0]
        self.assertTrue(saved["resolved"])
        self.assertEqual(len(saved["messages"]), 2)

    def test_a_comment_closed_empty_leaves_nothing(self):
        panel = self.pane._comment_panel
        count = self.scene.undo.count()
        self.pane.view.set_tool("comment")
        from PySide6.QtTest import QTest
        QTest.mouseClick(self.pane.view.viewport(), Qt.LeftButton, pos=self.pane.view.viewport().rect().center())
        self.assertIsNotNone(panel.comment)
        panel.close_panel()
        self.assertEqual([i for i in self.scene.board_items() if i.kind == "comment"], [])
        self.assertEqual(self.scene.undo.count(), count)


class PageAndSettingsTest(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)
        self.host = QWidget()
        self.host.resize(900, 600)
        self.addCleanup(self.host.deleteLater)

    def test_page_color_is_saved_undoable_and_resettable(self):
        path = board.create_board_file(self.dir / "b")
        pane = BoardPane(self.host)
        pane.open(path)
        scene = pane.scene
        self.assertEqual(scene.background.name(), model.MIRO_BACKGROUND)
        scene.set_page({"background": "#e9eef6"})
        self.assertEqual(scene.background.name(), "#e9eef6")
        self.assertTrue(pane.save())
        self.assertEqual(serialization.load(path)["page"]["background"], "#e9eef6")
        scene.undo.undo()
        self.assertEqual(scene.background.name(), model.MIRO_BACKGROUND)
        scene.undo.redo()
        scene.set_page({"background": None})
        self.assertEqual(scene.background.name(), model.MIRO_BACKGROUND)
        self.assertEqual(scene.snapshot([PAGE])[PAGE]["background"], None)

    def test_export_uses_the_page_background_or_transparency(self):
        scene = BoardScene()
        scene.add_new(model.new_item("sticky"))
        scene.set_page({"background": "#e9eef6"})
        out = self.dir / "a.png"
        export.export(scene, out)
        self.assertEqual(QColor(QImage(str(out)).pixel(2, 2)).name(), "#e9eef6")
        scene.set_page({"export_background": "transparent"})
        export.export(scene, out)
        self.assertEqual(QColor.fromRgba(QImage(str(out)).pixel(2, 2)).alpha(), 0)
        for suffix in (".svg", ".pdf"):
            target = self.dir / f"out{suffix}"
            export.export(scene, target)
            self.assertGreater(target.stat().st_size, 100, suffix)

    def test_general_snap_settings_are_declared_and_applied(self):
        import settings_store
        import settings_window_v2 as v2
        keys = {spec.key for spec in v2.CATALOG["MRO"]}
        self.assertEqual(keys, {"board_snap_enabled", "board_snap_objects", "board_snap_grid", "board_snap_resize",
                                "board_snap_guides", "board_snap_distance"})
        for key in keys:
            self.assertIn(key, settings_store.DEFAULT_SETTINGS)
        self.assertIn("board_pen_presets", settings_store._LIVE_STATE_KEYS)
        self.assertIn("MRO", [node.group for node in v2.MRO_TREE])            # onglet « Module MRO »
        pane = BoardPane(self.host)
        pane.apply_settings({"board_snap_enabled": False, "board_snap_distance": 14, "board_snap_grid": True})
        self.assertEqual(pane.scene.snap["distance"], 14)
        self.assertFalse(pane.scene.snap["enabled"])
        self.assertTrue(pane.scene.snap["grid"])


class MroSettingsSectionTest(unittest.TestCase):
    def test_rows_are_greyed_when_snap_is_off(self):
        import copy
        import settings_store
        import settings_window_v2 as v2
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        fields: dict = {}
        v2.build_group("MRO", v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], [], lambda: None)
        distance = fields["board_snap_distance"]
        self.assertTrue(distance.isEnabled())
        fields["board_snap_enabled"].setChecked(False)
        APP.processEvents()
        self.assertFalse(distance.isEnabled())


class MiroExchangeTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)

    def test_import_api_json(self):
        sample = {"data": [
            {"id": "1", "type": "sticky_note", "data": {"content": "<p>Idée</p><p>deux</p>", "shape": "square"},
             "style": {"fillColor": "light_yellow", "textAlign": "center", "textAlignVertical": "top"},
             "position": {"x": 0, "y": 0, "origin": "center"}, "geometry": {"width": 200, "height": 200}},
            {"id": "2", "type": "shape", "data": {"content": "", "shape": "round_rectangle"},
             "style": {"fillColor": "#ff0000", "borderStyle": "dashed"},
             "position": {"x": 400, "y": 0, "origin": "center"}, "geometry": {"width": 100, "height": 50}},
            {"id": "3", "type": "image", "data": {"imageUrl": "https://example.com/a.png"},
             "position": {"x": 0, "y": 300}, "geometry": {"width": 80, "height": 60}},
            {"id": "4", "type": "mindmap_node"},
            {"id": "5", "type": "connector", "startItem": {"id": "1"}, "endItem": {"id": "2"}, "shape": "elbowed",
             "style": {"endStrokeCap": "stealth"}}]}
        path = self.dir / "miro.json"
        path.write_text(json.dumps(sample), encoding="utf-8")
        items, report = miro_io.import_api_json(path)
        by_type = {i["type"]: i for i in items}
        self.assertEqual(by_type["sticky"]["text"], "Idée\ndeux")
        self.assertEqual((by_type["sticky"]["x"], by_type["sticky"]["y"]), (-100.0, -100.0))   # centre -> coin
        self.assertEqual(by_type["sticky"]["color"], "#fff9b1")
        self.assertEqual(by_type["shape"]["shape"], "round")
        self.assertEqual(by_type["shape"]["stroke_style"], "dashed")
        self.assertEqual(by_type["image"]["source_url"], "https://example.com/a.png")
        self.assertEqual(by_type["connector"]["style"], "elbow")
        self.assertEqual(report["ignored"], {"mindmap_node": 1})
        self.assertIn("Ignorés", miro_io.describe(report))

    def test_export_api_json_reports_what_miro_cannot_take(self):
        data = model.empty_board()
        a, b = model.new_item("sticky", color="#123456"), model.new_item("shape", radius=8.0)
        data["items"] = [a, b, model.new_item("connector", src={"item": a["id"]}, dst={"item": b["id"]}),
                         model.new_item("ink", points=[[0, 0], [1, 1]]), model.new_item("comment")]
        payload, report = miro_io.export_api_json(data)
        endpoints = [r["endpoint"].rsplit("/", 1)[1] for r in payload["requests"]]
        self.assertEqual(endpoints, ["sticky_notes", "shapes", "connectors"])
        self.assertEqual(len(report["ignored"]), 2)
        self.assertTrue(any("arrondi" in c for c in report["changed"]))


class _PaneCase(unittest.TestCase):
    def setUp(self):
        app_style.apply_style(APP)
        self.host = QWidget()
        self.host.resize(1200, 800)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(drop_panes)
        self.path = board.create_board_file(self.dir / "b")
        self.pane = BoardPane(self.host)
        self.pane.open(self.path)
        self.pane.fit()
        self.pane.show()
        self.scene, self.view = self.pane.scene, self.pane.view
        settle(0.05)


class TextZoomAndEditTest(_PaneCase):
    def test_texts_stay_drawn_at_every_zoom(self):
        note = self.scene.add_new(model.new_item("sticky", text="lisible ?"))
        frame = self.scene.add_new(model.new_item("frame", x=-400, y=-400))
        self.scene.set_page({"zoom_min": 0.001, "zoom_max": 20.0})
        for zoom in (0.001, 0.05, 0.17, 1.0, 20.0):
            self.view.set_zoom(zoom)
            self.assertTrue(note.text_item.isVisible(), zoom)
            self.assertTrue(frame.text_item.isVisible(), zoom)
            self.view.viewport().grab()
        self.view.set_zoom(20.0)
        title = frame.text_item.font()
        self.assertLess(title.pointSizeF() if title.pointSizeF() > 0 else title.pixelSize(), 4)   # 14 px a l'ecran

    def test_context_bar_is_complete_while_editing_and_click_away_ends(self):
        from PySide6.QtTest import QTest
        shape = self.scene.add_new(model.new_item("shape", text="Forme", x=0, y=0))
        settle(0.05)
        viewport = self.view.viewport()
        pos = self.view.mapFromScene(shape.scene_rect().center())
        QTest.mouseClick(viewport, Qt.LeftButton, pos=pos)
        settle(0.05)
        QTest.mouseDClick(viewport, Qt.LeftButton, pos=pos)
        settle(0.05)
        self.assertTrue(shape.text_item.editing())
        bar = self.pane._contextbar
        self.assertGreater(bar.width(), 300)                              # plus de barre de 12 x 12 px
        self.assertTrue(all(bar.layout().itemAt(i).widget().isVisible() for i in range(bar.layout().count())))
        QTest.keyClicks(viewport, " !")
        count = self.scene.undo.count()
        QTest.mouseClick(viewport, Qt.LeftButton, pos=self.view.mapFromScene(QPointF(900, 700)))
        settle(0.05)
        self.assertFalse(shape.text_item.editing())
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(shape.item_id).data["text"], "Forme")


class ZoomLimitsTest(_PaneCase):
    def test_defaults_and_old_files(self):
        self.assertEqual(self.view.limits(), (0.1, 4.0))
        self.assertEqual(model.zoom_limits({}), (0.1, 4.0))
        self.assertEqual(model.zoom_limits({"zoom_min": 2.0, "zoom_max": 1.0}), (0.1, 4.0))   # plage invalide
        self.view.set_zoom(10.0)
        self.assertEqual(self.view.zoom(), 4.0)

    def test_page_limits_extend_clamp_and_persist(self):
        self.scene.set_page({"zoom_min": 0.001, "zoom_max": 20.0})
        self.view.set_zoom(0.001)
        self.assertAlmostEqual(self.view.zoom(), 0.001)
        from fm_board.ui import format_zoom, parse_percent
        self.assertEqual(format_zoom(0.001), "0,1 %")
        self.assertEqual(format_zoom(20.0), "2000 %")
        self.assertEqual(parse_percent("0,1 %"), 0.001)
        self.view.set_zoom(20.0)
        self.scene.set_page({"zoom_max": 2.0})                            # le zoom courant y est ramene
        self.assertEqual(self.view.zoom(), 2.0)
        self.scene.undo.undo()
        self.assertEqual(self.view.limits()[1], 20.0)
        self.assertTrue(self.pane.save(with_view=True))
        data = serialization.load(self.path)
        self.assertEqual((data["page"]["zoom_min"], data["page"]["zoom_max"]), (0.001, 20.0))
        self.assertEqual(data["view"]["zoom"], 2.0)

    def test_zoom_around_the_cursor_stays_precise(self):
        self.scene.set_page({"zoom_min": 0.001, "zoom_max": 20.0})
        anchor = QPointF(300, 200)
        before = self.view.viewportTransform().inverted()[0].map(anchor)
        for _ in range(30):
            self.view.zoom_by(0.8, anchor)
        after = self.view.viewportTransform().inverted()[0].map(anchor)
        self.assertLess(abs(after.x() - before.x()) * self.view.zoom(), 1.5)  # moins d'un pixel et demi a l'ecran

    def test_percent_field_rejects_invalid_ranges(self):
        from fm_board.ui import _PercentField
        field = _PercentField(0.1, lambda v: None if 0 < v < 4 else "hors plage")
        got = []
        field.committed.connect(got.append)
        field.field.setText("0,5")
        field._commit()
        field.field.setText("-3")
        field._commit()
        field.field.setText("900")
        field._commit()
        self.assertEqual(got, [0.005])
        self.assertEqual(field.field.text(), "0,5 %")


class ArrowCapTest(_PaneCase):
    def test_caps_are_saved_undoable_and_compatible(self):
        from fm_miro.items import CAP_KINDS
        arrow = self.scene.add_new(model.new_item("connector", src={"x": 0, "y": 0}, dst={"x": 300, "y": 0}))
        self.assertEqual(arrow.caps(), ("none", "filled"))
        for kind in CAP_KINDS:
            self.scene.change_items([arrow], lambda i, k=kind: i.data.update(start_cap=k, end_cap=k), "Pointe")
            arrow = self.scene.item(arrow.item_id)
            self.view.viewport().grab()
        self.scene.change_items([arrow], lambda i: i.data.update(start_cap="circle", end_cap="open"), "Pointe")
        self.scene.live_change("cap_size", [arrow], lambda i: i.data.update(cap_size=33.0), "Taille")
        self.scene.commit_live()
        saved = {d["id"]: d for d in self.scene.to_data()["items"]}[arrow.item_id]
        self.assertEqual((saved["start_cap"], saved["end_cap"], saved["cap_size"]), ("circle", "open", 33.0))
        self.assertEqual((saved["arrow_start"], saved["arrow_end"]), (True, True))     # anciennes versions
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(arrow.item_id).data["cap_size"], 12.0)
        old = model.normalize_item({"id": "o", "type": "connector", "arrow_start": True, "arrow_end": False,
                                    "width": 2})
        self.assertEqual((old["start_cap"], old["end_cap"], old["cap_size"]), ("filled", "none", 12.4))

    def test_short_arrows_and_hit_area(self):
        short = self.scene.add_new(model.new_item("connector", src={"x": 0, "y": 0}, dst={"x": 8, "y": 0},
                                                  start_cap="diamond", end_cap="filled", cap_size=60))
        line, heads, _points = short._geometry()
        self.assertEqual(len(heads), 2)
        self.assertLessEqual(heads[0][0].boundingRect().width(), 8.1)       # pointes reduites a la fleche
        long = self.scene.add_new(model.new_item("connector", src={"x": 0, "y": 100}, dst={"x": 400, "y": 100},
                                                 end_cap="diamond", cap_size=40, style="curved"))
        self.assertTrue(long.shape().contains(QPointF(380, 100 + 10)))     # la pointe se clique
        self.scene.set_page({"zoom_min": 0.001, "zoom_max": 20.0})
        for zoom in (0.001, 20.0):
            self.view.set_zoom(zoom)
            self.view.viewport().grab()


class FrameFormatTest(_PaneCase):
    def test_paper_ratio_is_exact_and_orientation_switches(self):
        frame = self.scene.add_new(model.new_item("frame", w=800, h=600))
        frame.setSelected(True)
        self.pane._set_frame_format({"format": "A4", "orientation": "portrait"}, create=False)
        frame = self.scene.item(frame.item_id)
        self.assertAlmostEqual(frame.data["w"] / frame.data["h"], 210 / 297, places=3)
        self.assertTrue(frame.data["ratio_locked"])
        self.pane._set_frame_format({"orientation": "landscape"}, create=False)
        frame = self.scene.item(frame.item_id)
        self.assertAlmostEqual(frame.data["w"] / frame.data["h"], 297 / 210, places=3)
        self.pane._set_frame_format({}, create=False, real_size=True)
        frame = self.scene.item(frame.item_id)
        self.assertAlmostEqual(frame.data["w"], 297 * 96 / 25.4, places=1)
        self.scene.undo.undo()
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(frame.item_id).data["format"], "A4")

    def test_locked_ratio_resize_and_free_resize(self):
        frame = self.scene.add_new(model.new_item("frame", w=400, h=400, format="square", ratio_locked=True))
        self.assertTrue(frame.KEEP_RATIO)
        self.assertIsNone(frame.handle_at(QPointF(400, 200)))              # pas de bord tirable verrouille
        self.scene.change_items([frame], lambda i: i.data.update(ratio_locked=False), "Proportions")
        self.assertFalse(self.scene.item(frame.item_id).KEEP_RATIO)
        self.assertFalse(model.normalize_item({"id": "f", "type": "frame"})["ratio_locked"])  # anciens cadres

    def test_custom_ratio_validation(self):
        self.assertEqual(model.parse_ratio("16:9"), (16.0, 9.0))
        self.assertEqual(model.parse_ratio("2,35/1"), (2.35, 1.0))
        for bad in ("0:9", "-4:3", "abc", "16:0"):
            self.assertIsNone(model.parse_ratio(bad), bad)
        self.assertAlmostEqual(model.frame_ratio({"format": "custom", "ratio": [16, 9], "orientation": "portrait"}),
                               9 / 16)

    def test_creation_with_a_format(self):
        from PySide6.QtTest import QTest
        self.view.frame_format.update(format="A5", orientation="portrait", ratio_locked=True)
        self.view.set_tool("frame")
        QTest.mouseClick(self.view.viewport(), Qt.LeftButton, pos=self.view.viewport().rect().center())
        frame = [i for i in self.scene.board_items() if i.kind == "frame"][0]
        self.assertAlmostEqual(frame.data["w"], 148 * 96 / 25.4, places=1)
        self.assertAlmostEqual(frame.data["h"], 210 * 96 / 25.4, places=1)


class FontPickerTest(_PaneCase):
    def test_list_previews_and_missing_font(self):
        from fm_board.ui import FontPicker, installed_families
        families = installed_families()
        if not families:
            self.skipTest("aucune police sur cette plateforme (offscreen)")
        self.assertIs(families, installed_families())                     # lue une seule fois
        picker = FontPicker("Police Imaginaire 42")
        roles = [picker.list.item(r).data(Qt.UserRole) for r in range(picker.list.count())]
        self.assertEqual(roles[0], "missing")
        self.assertEqual(picker.list.currentItem().text(), "Police Imaginaire 42")
        picker.list.grab()
        picker.filter.setText(families[0][:3])
        visible = [picker.list.item(r).text() for r in range(picker.list.count()) if not picker.list.item(r).isHidden()]
        self.assertIn(families[0], visible)

    def test_choosing_applies_to_every_selected_text(self):
        a = self.scene.add_new(model.new_item("shape", text="a"))
        b = self.scene.add_new(model.new_item("sticky", text="b"), select=False)
        a.setSelected(True)
        b.setSelected(True)
        family = "Police Imaginaire 7"
        self.pane._change(self.pane._targets(("sticky", "text", "shape")),
                          lambda i: i.data.update(font_family=family), "Police")
        self.assertEqual({self.scene.item(i.item_id).data["font_family"] for i in (a, b)}, {family})
        note = self.scene.add_new(model.new_item("text", text="x", font_family="Police Imaginaire 42"))
        self.assertTrue(self.pane.save())
        saved = {d["id"]: d for d in serialization.load(self.path)["items"]}[note.item_id]
        self.assertEqual(saved["font_family"], "Police Imaginaire 42")      # gardee malgre son absence


class MroIconsTest(_PaneCase):
    def test_icon_rows_and_provider(self):
        import settings_window_v2 as v2
        keys = {spec.params["ui_key"] for spec in v2.CATALOG["MRO : Icones"]}
        self.assertIn("ui_board_select", keys)
        self.assertIn("ui_board_lock", keys)
        self.assertIn(("Icônes", "MRO : Icones"), [(n.title, n.group) for n in v2.MRO_TREE])
        self.assertIn((v2.MRO_TAB, None), v2.SCOPES)
        self.assertNotIn("MRO", [n.title for n in v2.GENERAL_TREE])
        import fm_board.ui as board_ui_module
        asked = []
        red = __import__("PySide6.QtGui", fromlist=["QPixmap"]).QPixmap(20, 20)
        red.fill(QColor("red"))
        board_ui_module.ICON_PROVIDER = lambda kind, size: (asked.append(kind), red)[1] if kind == "select" else None
        self.addCleanup(setattr, board_ui_module, "ICON_PROVIDER", None)
        button = self.pane._tool_buttons["select"]
        image = button.grab().toImage()
        self.assertIn("select", asked)
        self.assertEqual(QColor(image.pixel(button.width() // 2, button.height() // 2)).name(), "#ff0000")
        from settings_v2_app import _default_glyph
        self.assertIsNotNone(_default_glyph("ui_board_lasso", 24))         # apercu du glyphe par defaut


class ClipboardTest(_PaneCase):
    def test_copy_gives_text_and_a_table_for_other_apps(self):
        a = self.scene.add_new(model.new_item("sticky", text="Un", x=0, y=0), select=False)
        b = self.scene.add_new(model.new_item("shape", text="Deux", x=300, y=0), select=False)
        a.setSelected(True)
        b.setSelected(True)
        self.view.copy_selection()
        mime = QApplication.clipboard().mimeData()
        self.assertEqual(mime.text(), "Un\nDeux")
        self.assertIn("<table><tr><td>Un</td></tr><tr><td>Deux</td></tr></table>", mime.html())
        self.view.paste()                                                  # entre boards : objets complets
        self.assertEqual(sorted(i.kind for i in self.scene.board_items()), ["shape", "shape", "sticky", "sticky"])

    def test_paste_tables_miro_html_images_and_text(self):
        from PySide6.QtCore import QMimeData
        clip = QApplication.clipboard()
        mime = QMimeData()
        mime.setHtml("<table><tr><td>A</td><td>B</td></tr><tr><td>C</td><td></td></tr></table>")
        mime.setText("A\tB\nC")
        clip.setMimeData(mime)
        self.view.paste()
        self.assertEqual(sorted(i.data["text"] for i in self.scene.board_items()), ["A", "B", "C"])
        mime = QMimeData()
        mime.setHtml('<meta charset="utf-8"><span data-meta="<--(miro-data-v1)abc(/miro-data-v1)-->"></span>'
                     '<div><div>Post-it Miro</div></div><div><div>Autre</div></div>')
        clip.setMimeData(mime)
        self.view.paste()
        texts = sorted(i.data["text"] for i in self.scene.board_items() if i.kind == "sticky")
        self.assertIn("Post-it Miro", texts)
        image = QImage(30, 20, QImage.Format_RGB32)
        image.fill(QColor("blue"))
        clip.setImage(image)
        self.view.paste()
        self.assertEqual(len([i for i in self.scene.board_items() if i.kind == "image"]), 1)
        clip.setText("du texte simple")
        self.view.paste()
        self.assertIn("du texte simple", [i.data.get("text") for i in self.scene.board_items()])

    def test_copy_as_image(self):
        note = self.scene.add_new(model.new_item("sticky", text="img"))
        self.view.copy_selection_image()
        image = QApplication.clipboard().image()
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), note.data["w"])


class ArrowEndsTest(_PaneCase):
    def _drag(self, start, end, modifiers=Qt.NoModifier):
        from PySide6.QtTest import QTest
        viewport = self.view.viewport()
        QTest.mousePress(viewport, Qt.LeftButton, modifiers, self.view.mapFromScene(start))
        for t in (0.3, 0.6, 1.0):
            point = QPointF(start.x() + (end.x() - start.x()) * t, start.y() + (end.y() - start.y()) * t)
            QTest.mouseMove(viewport, self.view.mapFromScene(point))
        QTest.mouseRelease(viewport, Qt.LeftButton, modifiers, self.view.mapFromScene(end))
        settle(0.02)

    def test_ends_are_grabbed_moved_attached_and_undone(self):
        box = self.scene.add_new(model.new_item("shape", x=300, y=-50, w=120, h=100), select=False)
        arrow = self.scene.add_new(model.new_item("connector", src={"x": -200, "y": 0}, dst={"x": 0, "y": 0}),
                                   select=False)
        self.scene.clearSelection()
        settle(0.02)
        count = self.scene.undo.count()
        self._drag(QPointF(0, 0), QPointF(360, 0))                         # extremite saisie sans selection prealable
        arrow = self.scene.item(arrow.item_id)
        self.assertEqual(arrow.data["dst"], {"item": box.item_id})        # rattachee a la forme
        self.assertEqual(self.scene.undo.count(), count + 1)
        box.setPos(300, 200)                                              # elle suit l'objet
        self.assertGreater(arrow._line.p2().y(), 150)
        self._drag(QPointF(-200, 0), QPointF(-150, -120))                  # l'autre extremite : libre
        self.assertEqual(self.scene.item(arrow.item_id).data["src"], {"x": -150.0, "y": -120.0})
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(arrow.item_id).data["src"], {"x": -200, "y": 0})
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(arrow.item_id).data["dst"], {"x": 0, "y": 0})
        self.scene.undo.redo()
        self.assertTrue(self.pane.save())
        saved = {d["id"]: d for d in serialization.load(self.path)["items"]}[arrow.item_id]
        self.assertEqual(saved["dst"], {"item": box.item_id})

    def test_alt_drops_a_free_end_even_over_an_object(self):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent
        box = self.scene.add_new(model.new_item("shape", x=300, y=-50, w=120, h=100), select=False)
        arrow = self.scene.add_new(model.new_item("connector", src={"x": -200, "y": 0}, dst={"x": 0, "y": 0}))

        def event(kind, point, modifiers):
            ev = QGraphicsSceneMouseEvent(kind)
            ev.setScenePos(point)
            ev.setButton(Qt.LeftButton)
            ev.setButtons(Qt.LeftButton)
            ev.setModifiers(modifiers)
            return ev
        arrow.mousePressEvent(event(QEvent.GraphicsSceneMousePress, QPointF(0, 0), Qt.NoModifier))
        arrow.mouseMoveEvent(event(QEvent.GraphicsSceneMouseMove, QPointF(360, 0), Qt.NoModifier))
        self.assertEqual(arrow.data["dst"], {"item": box.item_id})        # au-dessus de la forme : rattachee
        self.assertIsNotNone(self.scene.highlight)
        arrow.mouseMoveEvent(event(QEvent.GraphicsSceneMouseMove, QPointF(360, 0), Qt.AltModifier))
        self.assertNotIn("item", arrow.data["dst"])                       # Alt : laissee libre
        arrow.mouseReleaseEvent(event(QEvent.GraphicsSceneMouseRelease, QPointF(360, 0), Qt.AltModifier))
        self.assertIsNone(self.scene.highlight)


class RatioSnapTest(unittest.TestCase):
    def test_locked_ratio_survives_snapping_for_every_corner_and_orientation(self):
        from PySide6.QtGui import QTransform
        scene = BoardScene()
        scene.visible_rect = QRectF(-3000, -3000, 6000, 6000)
        scene.add_new(model.new_item("shape", x=1003, y=-500, w=50, h=2000), select=False)   # bord vertical a 1003
        scene.add_new(model.new_item("shape", x=-500, y=703, w=3100, h=40), select=False)   # bord horizontal a 703
        for ratio in (16 / 9, 9 / 16):
            frame = scene.add_new(model.new_item("frame", x=0, y=0, w=400, h=400 / ratio, format="custom",
                                                 ratio=[16, 9], ratio_locked=True), select=False)
            transform = QTransform.fromTranslate(0, 0)
            for handle, rect in (("br", QRectF(0, 0, 1000, 1000 / ratio)), ("tr", QRectF(0, -600, 998, 998 / ratio)),
                                 ("bl", QRectF(-600, 0, 1001 + 600, 1601 / ratio)), ("tl", QRectF(-5, -5, 700, 700 / ratio))):
                fixed = {"br": rect.topLeft(), "tr": rect.bottomLeft(), "bl": rect.topRight(), "tl": rect.bottomRight()}
                out = scene.snap_resize(frame, rect, transform, handle, Qt.NoModifier, ratio=ratio)
                self.assertAlmostEqual(out.width() / out.height(), ratio, places=9, msg=handle)
                corner = {"br": out.topLeft(), "tr": out.bottomLeft(), "bl": out.topRight(), "tl": out.bottomRight()}
                self.assertAlmostEqual(corner[handle].x(), fixed[handle].x(), places=6, msg=handle)   # le coin fixe
                self.assertAlmostEqual(corner[handle].y(), fixed[handle].y(), places=6, msg=handle)   # ne glisse pas
            out = scene.snap_resize(frame, QRectF(0, 0, 1000, 1000 / ratio), transform, "br", Qt.NoModifier,
                                    ratio=ratio)
            self.assertTrue(abs(out.right() - 1003) < 1e-6 or abs(out.bottom() - 703) < 1e-6)   # aimante quand meme
            scene.delete_items([frame])


class MroToolbarAndMenuSettingsTest(_PaneCase):
    def test_border_color_row_sets_every_side(self):
        import copy
        import settings_menu
        import settings_store
        import settings_window_v2 as v2
        for group, key in (("Menu contextuel : Menu", "ctx_menu_border_color"),
                           ("MRO : Menu contextuel : Menu", "board_ctx_menu_border_color")):
            labels = [sp.label for sp in v2.CATALOG[group]]
            self.assertEqual(labels[labels.index("Bordures") + 1], "Couleur des bordures")
            settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
            fields = {}
            v2.build_group(group, v2.ScopeValues(settings, None), settings["colors"], fields, {}, [], [],
                           lambda: None)
            fields[key].setValue("#ff0000")
            fields[key].changed.emit("#ff0000")
            sides = fields[key.replace("_color", "_enabled")]
            self.assertEqual(set(sides.sides.value().values()), {"#ff0000"})   # posee sur les 4 cotes
        values = dict(settings_store.DEFAULT_SETTINGS, board_ctx_menu_border_color="#00ff00",
                      board_ovr_ctx_menu_border_color=True)
        old = settings_menu._STATE["values"]
        settings_menu._STATE["values"] = lambda: values
        try:
            self.assertEqual(set(settings_menu.menu_look("board")["border_colors"].values()), {"#00ff00"})
            self.assertEqual(set(settings_menu.menu_look(None)["border_colors"].values()), {"#2c3034"})
        finally:
            settings_menu._STATE["values"] = old

    def test_toolbars_follow_their_settings_at_once(self):
        bar = self.pane._toolbar
        self.assertEqual(bar.look["bg"], "#16181a")                       # apparence d'origine par defaut
        self.pane.apply_settings({"board_toolbar_bg_color": "#ff0000",
                                  "board_toolbar_corner_radius": {"top_left": 8, "top_right": 8, "bottom_right": 8,
                                                                  "bottom_left": 8},
                                  "board_toolbar_text_font_size": 17, "board_toolbar_text_font_color": "#00ff00",
                                  "board_toolbar_shadow_enabled": {"top": True, "right": True, "bottom": True,
                                                                   "left": True},
                                  "board_toolbar_shadow_size": 12})
        self.assertEqual(bar.look["bg"], "#ff0000")
        image = bar.grab().toImage()
        self.assertEqual(QColor(image.pixel(bar.width() // 2, 3)).name(), "#ff0000")
        self.assertIsNotNone(bar.look["shadow"])
        self.assertTrue(bar._shadow.isVisible())
        shape = self.scene.add_new(model.new_item("shape", text="x"))
        settle(0.05)
        from fm_board.ui import _TextButton
        buttons = self.pane._contextbar.findChildren(_TextButton)
        self.assertTrue(buttons)
        self.assertEqual(buttons[0].font().pixelSize() or round(buttons[0].font().pointSizeF() * 4 / 3), 17)
        self.assertIsNotNone(shape)

    def test_board_menus_follow_the_app_unless_overridden(self):
        import settings_menu
        import settings_store
        import settings_window_v2 as v2
        values = dict(settings_store.DEFAULT_SETTINGS)
        values.update(ctx_menu_bg="#111111", board_ctx_menu_bg="#ff00ff")
        self.assertEqual(settings_menu.scoped_values(values, "board")["ctx_menu_bg"], "#111111")   # suit l'appli
        values["board_ovr_ctx_menu_bg"] = True
        self.assertEqual(settings_menu.scoped_values(values, "board")["ctx_menu_bg"], "#ff00ff")   # override
        self.assertEqual(settings_menu.scoped_values(values, None)["ctx_menu_bg"], "#111111")      # l'appli : rien
        menu = board_ui._menu(self.pane, "test")
        self.assertEqual(settings_menu.menu_scope(menu), "board")
        for group in ("Menu contextuel : Menu", "Menu contextuel : Lignes", "Menu contextuel : Survol",
                      "Menu contextuel : Libelles", "Menu contextuel : Separateurs"):
            main = v2.CATALOG[group]
            scoped = v2.CATALOG[f"MRO : {group}"]
            self.assertEqual([s.label for s in main], [s.label for s in scoped])   # les memes tableaux
            for spec in scoped:
                self.assertEqual(spec.general_toggle, f"board_ovr_{spec.key[len('board_'):]}")
                for key in (spec.key, *spec.extra_keys, spec.general_toggle):
                    self.assertIn(key, settings_store.DEFAULT_SETTINGS, key)
        seeded = v2.ScopeValues({"ctx_menu_bg": "#111111", "board_ctx_menu_bg": "#ff00ff"}, None)
        self.assertEqual(seeded.seed("board_ctx_menu_bg", ""), "#111111")  # override coupe : la valeur de l'appli
        seeded.settings["board_ovr_ctx_menu_bg"] = True
        self.assertEqual(seeded.seed("board_ctx_menu_bg", ""), "#ff00ff")

    def test_settings_tables_build_with_override_toggles(self):
        import copy
        import settings_store
        import settings_window_v2 as v2
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        fields, toggles = {}, {}
        v2.build_group("MRO : Menu contextuel : Menu", v2.ScopeValues(settings, None), settings["colors"], fields,
                       toggles, [], [], lambda: None)
        self.assertIn("board_ovr_ctx_menu_bg", toggles)
        v2.build_group("MRO : Barres d'outils", v2.ScopeValues(settings, None), settings["colors"], fields, {},
                       [], [], lambda: None)
        self.assertIn("board_toolbar_bg_color", fields)


class ShiftSnapAndNegativeTest(_PaneCase):
    def _frame_drag(self, frame, points, modifiers_list):
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QGraphicsSceneMouseEvent

        def event(kind, point, modifiers):
            ev = QGraphicsSceneMouseEvent(kind)
            ev.setScenePos(point)
            ev.setPos(frame.mapFromScene(point))
            ev.setButton(Qt.LeftButton)
            ev.setButtons(Qt.LeftButton)
            ev.setModifiers(modifiers)
            return ev
        frame.mousePressEvent(event(QEvent.GraphicsSceneMousePress, points[0], Qt.NoModifier))
        for point, modifiers in zip(points[1:], modifiers_list):
            frame.mouseMoveEvent(event(QEvent.GraphicsSceneMouseMove, point, modifiers))
        return event

    def test_shift_turns_snapping_off_for_frames_and_keeps_the_locked_ratio(self):
        from PySide6.QtCore import QEvent
        self.scene.visible_rect = QRectF(-3000, -3000, 6000, 6000)
        self.scene.add_new(model.new_item("shape", x=1003, y=-500, w=50, h=2000), select=False)
        frame = self.scene.add_new(model.new_item("frame", x=0, y=0, w=400, h=225, format="custom", ratio=[16, 9],
                                                  ratio_locked=True))
        self.assertTrue(frame._handles_shown())
        event = self._frame_drag(frame, [QPointF(400, 225), QPointF(1000, 300)], [Qt.NoModifier])
        self.assertAlmostEqual(frame.data["w"], 1003)                     # aimante au bord voisin
        frame.refresh_gesture(Qt.ShiftModifier)                           # Maj enfonce : aimantation coupee
        self.assertAlmostEqual(frame.data["w"], 1000)
        self.assertAlmostEqual(frame.data["w"] / frame.data["h"], 16 / 9)  # ratio verrouille garde
        frame.refresh_gesture(Qt.NoModifier)                              # Maj relache : elle reprend
        self.assertAlmostEqual(frame.data["w"], 1003)
        self.assertAlmostEqual(frame.data["w"] / frame.data["h"], 16 / 9)
        frame.mouseReleaseEvent(event(QEvent.GraphicsSceneMouseRelease, QPointF(1000, 300), Qt.NoModifier))
        self.assertEqual((frame.pos().x(), frame.pos().y()), (0, 0))      # le coin fixe n'a pas bouge

    def test_shift_does_not_change_an_unlocked_frame_ratio_and_still_keeps_shapes_ratio(self):
        frame = self.scene.add_new(model.new_item("frame", x=0, y=0, w=400, h=200))
        self._frame_drag(frame, [QPointF(400, 200), QPointF(700, 500)], [Qt.ShiftModifier])
        self.assertEqual((frame.data["w"], frame.data["h"]), (700, 500))   # libre : Maj ne garde pas le ratio

    def test_toolbar_button_toggles_negative_and_asks_the_app_to_save(self):
        written = []
        old = board_ui.SETTING_WRITER
        board_ui.SETTING_WRITER = lambda key, value: written.append((key, value))
        try:
            button = self.pane._invert_button
            self.assertIs(button.parentWidget(), self.pane._toolbar)
            button.click()
            self.assertTrue(self.pane._toolbar.look["invert"])
            button.click()
            self.assertFalse(self.pane._toolbar.look["invert"])
        finally:
            board_ui.SETTING_WRITER = old
        self.assertEqual(written, [("board_toolbar_invert", True), ("board_toolbar_invert", False)])
        from fm_board import model as board_model
        self.assertIn("invert", [kind for kind, _label in board_model.ICON_ROWS])   # icone reglable

    def test_override_toggles_are_type_1(self):
        import copy
        import settings_store
        import settings_window_v2 as v2
        settings = copy.deepcopy(settings_store.DEFAULT_SETTINGS)
        toggles = {}
        frame = v2.build_group("MRO : Menu contextuel : Survol", v2.ScopeValues(settings, None), settings["colors"],
                               {}, toggles, [], [], lambda: None)
        overrides = [t for k, t in toggles.items() if k.startswith("board_ovr_")]
        self.assertTrue(overrides)
        self.assertTrue(all(t._base_override == "toggle1" for t in overrides))
        self.assertIsNotNone(frame)

    def test_negative_icons_and_texts(self):
        from fm_board.ui import negative
        self.assertEqual(negative("#d6d9dc"), "#292623")
        button = self.pane._tool_buttons["hand"]

        def dark_pixels():
            image = button.grab().toImage()
            return sum(1 for x in range(image.width()) for y in range(image.height())
                       if QColor(image.pixel(x, y)).lightness() < 60 and QColor(image.pixel(x, y)).name() != "#16181a")
        light = dark_pixels()
        self.pane.apply_settings({"board_toolbar_invert": True})
        self.assertTrue(self.pane._toolbar.look["invert"])
        self.assertGreater(dark_pixels(), light)                          # le glyphe est passe en sombre
        self.pane.apply_settings({"board_toolbar_invert": False})
        self.assertEqual(dark_pixels(), light)                            # apparence normale retrouvee
        import settings_store
        self.assertIn("board_toolbar_invert", settings_store.DEFAULT_SETTINGS)


class BoardModeTest(unittest.TestCase):
    def setUp(self):
        import pipeline_browser as pb
        app_style.apply_style(APP)
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "set").mkdir()
        (self.root / "set" / "notes.txt").write_text("x", encoding="utf-8")
        self.win = pb.PipelineBrowser(self.root)
        self.win._idle_preview_scheduler.timer.stop()
        self.win.resize(1300, 800)
        self.win.show()
        self.addCleanup(self.win.deleteLater)
        settle()

    def _file_column(self):
        self.win._navigate_to(self.root / "set" / "notes.txt")
        settle(0.3)
        for column in reversed(self.win.columns):
            if Path(column.directory) == self.root / "set":
                return column
        self.fail([c.directory for c in self.win.columns])

    def test_create_mro_then_open_and_close_it(self):
        win = self.win
        column = self._file_column()
        self.assertFalse(win.btn_board.isEnabled())
        path = column._create_board_file("Atelier")
        self.assertEqual(path, self.root / "set" / "Atelier.mro")
        settle(0.3)
        self.assertTrue(win.btn_board.isEnabled())
        win.on_activated(path)
        settle(0.3)
        pane = win._board
        self.assertIsNotNone(pane)
        self.assertEqual(pane.geometry(), win.scroll.viewport().rect())
        group = win.titlebar.board_group()
        self.assertTrue(group.isVisible())
        from settings_store import load_settings
        settings = load_settings()
        settings["board_snap_distance"] = 12
        win._apply_settings(settings, {"board_snap_distance"})
        self.assertEqual(pane.scene.snap["distance"], 12)                 # Reglages > MRO en direct
        pane.scene.add_new(model.new_item("sticky", text="idée"))
        self.assertTrue(win._close_board())
        settle(0.3)
        self.assertIsNone(win._board)
        self.assertEqual(serialization.load(path)["items"][0]["text"], "idée")

    def test_double_click_on_a_dxf_opens_it_in_the_board(self):
        import ezdxf
        win = self.win
        source = self.root / "set" / "plan.dxf"
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (40, 0))
        doc.saveas(source)
        before = source.read_bytes()
        with mock.patch("pipeline_browser.open_path", side_effect=AssertionError("logiciel externe ouvert")):
            win.on_activated(source)                                    # lu en fond, puis ouvert
            for _ in range(200):
                settle(0.05)
                if win._board is not None:
                    break
        pane = win._board
        self.assertIsNotNone(pane)
        self.assertEqual(pane.source, source)
        self.assertEqual([i.data["type"] for i in pane.scene.board_items()], ["cad_line"])
        self.assertIn("1 objet(s)", win.path_label.text())
        self.assertTrue(win._close_board())                             # inchange : ferme sans question
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.root / "set").iterdir()), ["notes.txt", "plan.dxf"])


if __name__ == "__main__":
    unittest.main()
