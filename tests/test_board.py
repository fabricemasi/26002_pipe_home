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
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QWidget

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
        self.set_module("miro")             # les tests du board visent le module Miro (sa barre d'outils)


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
        self.assertEqual(path.name, "plan.brd")
        with self.assertRaises(FileExistsError):
            board.create_board_file(path)
        data = serialization.load(path)
        data["items"].append(model.new_item("sticky", text="é"))
        serialization.save(path, data)
        self.assertEqual(serialization.load(path)["items"][0]["text"], "é")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format"], "pipeline-board")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["plan.brd"])

    def test_legacy_mro_is_read_then_renamed_to_brd(self):
        """Ancien `.mro` : reconnu et lu ; un nouveau board demande en `.mro` est cree en `.brd` ; `migrate_legacy`
        RENOMME l'ancien fichier (meme nom, meme dossier d'images), sans ecraser un `.brd` existant."""
        old = self.dir / "ancien.mro"
        serialization.save(old, model.empty_board())
        self.assertTrue(board.is_board_file(old))
        self.assertTrue(board.is_board_file(self.dir / "x.brd"))
        self.assertEqual(serialization.load(old)["format"], "pipeline-board")
        self.assertEqual(board.create_board_file(self.dir / "neuf.mro").name, "neuf.brd")
        self.assertEqual(serialization.assets_dir(old), serialization.assets_dir(old.with_suffix(".brd")))
        new = serialization.migrate_legacy(old)
        self.assertEqual(new.name, "ancien.brd")
        self.assertFalse(old.exists())
        self.assertIsNone(serialization.migrated_path(new))
        serialization.save(old, model.empty_board())                    # .brd deja la : l'ancien reste en .mro
        self.assertEqual(serialization.migrate_legacy(old), old)
        self.assertTrue(old.exists())

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


class DeleteIndexTest(unittest.TestCase):
    """PLANTAGES a l'effacement (2026-11-03) : une zone d'element (`boundingRect`) changee sans `prepareGeometryChange`
    AVANT (marge des elements suivant le zoom, titre d'un cadre) laissait l'element dans des cases de l'index BSP de
    Qt apres son retrait : pointeur mort une fois l'element detruit, relu a la peinture / au survol suivants. Un
    element retire ne doit plus jamais etre trouve par `items()` (les elements sont gardes en vie pour le verifier)."""

    def _stale(self, scene, items):
        found = []
        for item in items:
            rect = item.sceneBoundingRect()                  # detache : marge de 3 (zoom 1) > marge au zoom 4
            if item in scene.items(rect.adjusted(-60, -60, 60, 60)):
                found.append(item.kind)
        return found

    def test_removed_items_leave_the_index_after_zooms(self):
        import random
        rnd = random.Random(1)
        scene = BoardScene()
        items = [scene._add(model.new_item(rnd.choice(["sticky", "text", "shape", "ink", "frame"]),
                                           x=rnd.uniform(-5000, 5000), y=rnd.uniform(-5000, 5000),
                                           w=rnd.uniform(20, 300), h=rnd.uniform(20, 300),
                                           points=[[0, 0], [40, 20], [80, 5]], title="un titre assez long"))
                 for _ in range(2500)]
        for item in items[:40]:
            item.setSelected(True)
        for zoom in (0.1, 0.13, 4.0, 3.1):                   # dezoom puis zoom (deux paliers, puis le meme)
            scene.set_zoom(zoom)
            scene.items(scene.sceneRect())                   # index refait a chaque etape
        for item in items:
            if item.kind == "frame":
                item.text_item.setPlainText("t")             # titre raccourci : zone du cadre plus petite
        scene.items(scene.sceneRect())
        removed = items[:600]
        scene.delete_items(removed)                          # (deleteLater : encore en vie jusqu'au retour a la boucle)
        self.assertEqual(self._stale(scene, removed), [])

    def test_removed_frame_leaves_the_index_after_a_shorter_title(self):
        import random
        rnd = random.Random(2)
        scene = BoardScene()
        title = "un titre bien plus large que son cadre"
        frames = [scene._add(model.new_item("frame", x=rnd.uniform(-5000, 5000), y=rnd.uniform(-5000, 5000),
                                            w=8, h=8, title=title)) for _ in range(1500)]
        scene.items(scene.sceneRect())
        for frame in frames:
            frame.text_item.setPlainText("t")                # zone du cadre plus etroite (frappe)
        scene.items(scene.sceneRect())
        removed = frames[:500]
        scene.delete_items(removed)
        for frame in removed:
            frame.text_item.setPlainText(title)              # rallonge, detache : la recherche atteint ses anciennes cases
        self.assertEqual(self._stale(scene, removed), [])


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
        manager = self.pane._miro_bars.manager
        tips = {manager.widgets[key].toolTip() for key in manager.dynamic["ctx"]}
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
                                "board_snap_guides", "board_snap_distance",
                                "board_snap_doc_guides", "board_snap_inner_guides",
                                "board_snap_frame_guides"})                              # lignes des guides par sorte
        keys |= {key for spec in v2.CATALOG["MRO"] for key in spec.extra_keys}
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


class ModuleSelectorTest(_PaneCase):
    """Selecteur de modules du board (demande de l'utilisateur) : a l'ouverture aucune barre d'outils, deux boutons
    Miro / CAD ; la barre d'un module s'affiche quand il est active ; par module, griser ou masquer ses elements."""

    def test_no_toolbar_at_opening_then_the_toolbar_of_the_chosen_module(self):
        pane = board_ui.BoardPane(self.host)                    # sans le module Miro des autres tests
        _PANES.append(pane)
        pane.open(self.path)
        pane.show()
        settle(0.05)
        self.assertIsNone(pane.module)
        self.assertFalse(pane._toolbar.isVisible())
        self.assertTrue(pane._modulebar.isVisible())
        self.assertNotIn("cad", pane._tool_buttons)              # plus d'icone CAD dans la barre de Miro
        note = pane.scene.add_new(model.new_item("sticky", text="x"))
        note.setSelected(True)
        pane._sync_context_bar()
        self.assertFalse(pane._contextbar.isVisible())           # aucun module : aucune barre
        miro, cad = pane._module_buttons["miro"][0], pane._module_buttons["cad"][0]
        miro.click()
        self.assertEqual(pane.module, "miro")
        self.assertTrue(pane._toolbar.isVisible())
        cad.click()
        self.assertEqual(pane.module, "cad")
        self.assertTrue(pane.cad_active())
        self.assertFalse(pane._toolbar.isVisible())
        self.assertTrue(pane.cad.ui.toolbar.isVisible())
        cad.click()                                              # re-clic : plus aucun module
        self.assertIsNone(pane.module)
        self.assertFalse(pane.cad_active())
        self.assertFalse(pane._toolbar.isVisible())
        pane.view.set_tool("sticky")                             # outil choisi au clavier : le module Miro s'active
        self.assertEqual(pane.module, "miro")
        self.assertTrue(pane._toolbar.isVisible())

    def test_without_a_module_nothing_is_selected_moved_or_resized(self):
        """Demande de l'utilisateur, 2026-11-06 : « quand aucun module n'est actif, on peut quand même sélectionner et
        dimensionner des éléments ; je ne veux pas ça ». Le double-clic ouvre l'élément comme avant, sans le choisir."""
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        pane = self.pane
        note = pane.scene.add_new(model.new_item("sticky", text="x", x=0, y=0))
        note.setSelected(True)
        pane.set_module(None)
        self.assertFalse(note.isSelected())                      # module quitté : plus rien de choisi
        view, viewport = pane.view, pane.view.viewport()
        center = view.mapFromScene(note.mapToScene(note.content_rect().center()))
        QTest.mouseClick(viewport, Qt.LeftButton, pos=center)    # vrai clic
        self.assertFalse(note.isSelected())
        start = QPointF(note.pos())
        QTest.mousePress(viewport, Qt.LeftButton, pos=center)    # glisser : l'élément ne bouge pas
        for k in range(1, 6):
            QTest.mouseMove(viewport, center + QPoint(12 * k, 8 * k))
        QTest.mouseRelease(viewport, Qt.LeftButton, pos=center + QPoint(60, 40))
        self.assertEqual(note.pos(), start)
        self.assertFalse(note.isSelected())
        corner = view.mapFromScene(note.mapToScene(note.content_rect().topLeft())) - QPoint(60, 60)
        QTest.mousePress(viewport, Qt.LeftButton, pos=corner)    # rectangle de sélection : rien
        QTest.mouseMove(viewport, center + QPoint(80, 80))
        QTest.mouseRelease(viewport, Qt.LeftButton, pos=center + QPoint(80, 80))
        self.assertEqual(pane.scene.selectedItems(), [])
        QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)       # Ctrl + A : rien
        self.assertEqual(pane.scene.selectedItems(), [])
        self.assertIsNone(pane.module)
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication

        def send(kind, pos, button, buttons):
            p = QPointF(pos)
            QApplication.sendEvent(viewport, QMouseEvent(kind, p, viewport.mapToGlobal(p), button, buttons,
                                                         Qt.NoModifier))
        send(QEvent.MouseButtonDblClick, center, Qt.LeftButton, Qt.LeftButton)   # double-clic puis glisser
        for k in range(1, 6):
            send(QEvent.MouseMove, center + QPoint(12 * k, 8 * k), Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, center + QPoint(60, 40), Qt.LeftButton, Qt.NoButton)
        self.assertEqual(note.pos(), start)                      # ouvert comme avant, ni choisi ni déplacé
        self.assertFalse(note.isSelected())
        self.assertIsNone(pane.module)

    def test_fade_and_hide_the_elements_of_a_module(self):
        note = self.scene.add_new(model.new_item("sticky", text="x"))
        note.setSelected(True)
        _icon, hide, fade, _solo = self.pane._module_buttons["miro"]
        fade.click()
        self.assertAlmostEqual(note.opacity(), 0.3)
        self.assertFalse(note.isEnabled())
        self.assertFalse(note.isSelected())
        note.setSelected(True)
        self.assertFalse(note.isSelected())                      # grise : ni selectionnable...
        spot = self.view.mapFromScene(note.sceneBoundingRect().center())
        self.assertIsNone(self.view._item_at(spot))              # ... ni attrape a la souris
        hide.click()
        self.assertFalse(note.isVisible())
        later = self.scene.add_new(model.new_item("shape", text="y", x=400))
        self.assertFalse(later.isVisible())                      # un element neuf suit son module
        hide.click()
        fade.click()
        for item in (note, later):
            self.assertTrue(item.isVisible())
            self.assertTrue(item.isEnabled())
            self.assertAlmostEqual(item.opacity(), 1.0)
        self.assertIs(self.view._item_at(spot), note)

    def test_isolate_reset_and_fold_the_module_bar(self):
        """Barre des modules (maquette 2026-10-31) : isoler (bouton ou Alt + clic), pastille « Isolé », tout
        reinitialiser, languette qui replie la barre entierement."""
        pane = self.pane
        note = self.scene.add_new(model.new_item("sticky", text="x"))
        icon, hide, fade, solo = pane._module_buttons["cad"]
        solo.click()                                             # CAD isole : Miro masque
        self.assertTrue(self.scene.module_state["cad"]["solo"])
        self.assertFalse(note.isVisible())
        exit_button = pane._modulebar.solo_exit                  # barre toujours etroite : « Quitter l'isolation » en icone
        self.assertTrue(exit_button.isVisibleTo(pane._modulebar))
        self.assertLess(exit_button.geometry().bottom(), pane._modulebar.reset.mapTo(
            pane._modulebar, pane._modulebar.reset.rect().topLeft()).y())
        self.assertIn("CAD", exit_button.toolTip())
        self.assertTrue(pane._modulebar.rows["cad"].icon.solo_mark)    # point d'isolation sur l'icone
        self.assertEqual(pane._modulebar.rows["miro"].icon.state, "iso")
        hide.click()                                             # masquer ne vaut pas pour un module isole
        self.assertFalse(self.scene.module_look["cad"]["hide"])
        exit_button.click()                                      # quitter l'isolation : CAD reste masque
        self.assertTrue(note.isVisible())
        self.assertTrue(self.scene.module_look["cad"]["hide"])
        self.assertFalse(exit_button.isVisibleTo(pane._modulebar))
        pane._on_module_icon("miro", True)                       # Alt + clic : isoler
        self.assertTrue(self.scene.module_state["miro"]["solo"])
        pane._modulebar.reset.click()                            # tout afficher, sortir de l'isolation
        self.assertFalse(any(any(s.values()) for s in self.scene.module_state.values()))
        self.assertTrue(note.isVisible())
        pane._on_module_icon("tableur", False)                   # clic : activer le module
        self.assertEqual(pane.module, "tableur")
        pane._on_module_icon("tableur", False)
        self.assertIsNone(pane.module)
        self.assertGreaterEqual(pane.title_area().x(), pane._modulebar.geometry().right())
        wide = pane._modulebar.width()
        pane.toggle_module_look("cad", "solo")
        with mock.patch("settings_store.save_live_state") as save:
            pane._modulebar.fold.click()                         # (reglage « etroite ») : rien ne change de largeur
        save.assert_called_with("board_modulebar_folded", True)
        self.assertTrue(pane._modulebar.isVisible())
        self.assertEqual(pane._modulebar.width(), wide)
        self.assertFalse(pane._modulebar.rows["cad"].solo.isVisibleTo(pane._modulebar))
        self.assertTrue(pane._modulebar.rows["cad"].icon.solo_mark)
        self.assertTrue(exit_button.isVisibleTo(pane._modulebar))
        self.assertFalse(pane._modulebar.pill.isVisibleTo(pane._modulebar))
        self.assertLessEqual(exit_button.width(), pane._modulebar.width())
        exit_button.click()
        self.assertFalse(self.scene.module_state["cad"]["solo"])
        self.assertFalse(exit_button.isVisibleTo(pane._modulebar))
        pane.toggle_module_look("cad", "solo")
        self.assertGreaterEqual(pane.title_area().x(), pane._modulebar.geometry().right())
        with mock.patch("settings_store.save_live_state"):
            pane._modulebar.fold.click()
        self.assertEqual(pane._modulebar.width(), wide)
        self.assertTrue(pane._modulebar.rows["cad"].icon.solo_mark)    # toujours etroite : le point reste


class ModuleBarSettingsTest(_PaneCase):
    """Reglages : Board > Board > Barre de selection, appliques tout de suite au board ouvert."""

    def tearDown(self):
        self.pane.apply_settings({})                             # habillage commun : remis aux defauts

    def test_settings_restyle_the_bar_live(self):
        from fm_board import modulebar
        from fm_cad import cad_items
        pane = self.pane
        icon = pane._modulebar.rows["cad"].icon
        pane.apply_settings(dict(pane._settings, board_modulebar_color_cad="#ff0000", board_modulebar_icon_size=44,
                                 board_modulebar_buttons=False, board_modulebar_alt_solo=False,
                                 board_modules_fade_opacity=50))
        self.assertEqual(modulebar.LOOK["colors"]["cad"], "#ff0000")      # dominante du module
        self.assertEqual(icon.width(), 44)
        self.assertFalse(pane._modulebar.rows["cad"].vis.isVisibleTo(pane._modulebar))
        pane._on_module_icon("cad", True)                        # Alt + clic coupe : active seulement
        self.assertFalse(pane.scene.module_state["cad"]["solo"])
        self.assertEqual(pane.module, "cad")
        pane.set_module(None)
        note = pane.scene.add_new(model.new_item("sticky", text="x"))
        pane.toggle_module_look("miro", "fade")
        self.assertAlmostEqual(note.opacity(), 0.5)
        pane.apply_settings(dict(pane._settings, board_modules_fade_opacity=20))
        self.assertAlmostEqual(note.opacity(), 0.2)                # opacite des grises : a chaud
        pane.apply_settings({})
        self.assertAlmostEqual(cad_items.FADE_OPACITY, 0.3)

    def test_fade_saturation_and_tool_icon_color(self):
        """Saturation des elements grises (0 % = gris) et couleur des icones replier / reinitialiser."""
        from fm_board import scene as board_scene
        from fm_cad import cad_items
        pane = self.pane
        note = pane.scene.add_new(model.new_item("sticky", text="x"))
        pane.toggle_module_look("miro", "fade")
        self.assertIsNone(note.graphicsEffect())                 # 100 % (defaut) : aucun effet a peindre
        pane.apply_settings(dict(pane._settings, board_modules_fade_saturation=0,
                                 board_modulebar_tool_color="#ff00ff"))
        effect = note.graphicsEffect()
        self.assertIsInstance(effect, board_scene._FadeEffect)
        self.assertAlmostEqual(effect.strength(), 1.0)
        gray = QColor(cad_items.fade_ink("#ff0000"))
        self.assertEqual(gray.red(), gray.green())               # CAD : traits desatures
        self.assertEqual(pane._modulebar.reset.glyph_ink(False), "#ff00ff")
        self.assertEqual(pane._modulebar.fold.glyph_ink(False), "#ff00ff")
        pane.toggle_module_look("miro", "fade")                  # plus grise : effet retire
        self.assertIsNone(note.graphicsEffect())
        pane.apply_settings({})
        self.assertAlmostEqual(cad_items.FADE_SATURATION, 1.0)

    def test_save_state_signal_and_external_badge(self):
        """Etat d'enregistrement emis pour la barre d'etat de l'appli (le cartouche du board est cache) ; encart du
        mode de rendu montre par l'appli : celui du board se cache."""
        pane = self.pane
        states = []
        pane.saveStateChanged.connect(lambda text, dirty: states.append((text, dirty)))
        pane.scene.add_new(model.new_item("sticky", text="x"))
        settle(0.05)
        self.assertIn(("modifié", True), states)
        self.assertFalse(pane._title.isVisible())
        pane.set_external_badge(True)
        self.assertFalse(pane._badge.isVisible())
        self.assertIsNone(pane.view.gpu_badge)
        pane.set_external_badge(False)
        self.assertTrue(pane._badge.isVisible())

    def test_a_click_on_the_render_badge_switches_the_mode(self):
        """Clic sur l'encart OPEN GL / CLASSIQUE : l'autre mode, retenu dans le reglage."""
        pane = self.pane
        state = {"gpu": False}
        pane.view.gpu_active = lambda: state["gpu"]
        pane.view.set_gpu = lambda on: state.update(gpu=on) or True
        pane._badge.clicked.emit()
        self.assertTrue(state["gpu"])
        self.assertTrue(pane._settings["board_cad_gpu"])
        pane._badge.clicked.emit()
        self.assertFalse(state["gpu"])
        self.assertFalse(pane._settings["board_cad_gpu"])

    def test_fold_style_narrow_or_tab(self):
        """Barre repliee : etroite (1re maquette, defaut) ou cachee derriere une languette (2e), au choix."""
        pane = self.pane
        self.assertFalse(pane._module_tab.isVisible())           # defaut : etroite, pas de languette
        with mock.patch("settings_store.save_live_state"):
            pane.apply_settings(dict(pane._settings, board_modulebar_fold_style="tab"))
            self.assertTrue(pane._module_tab.isVisible())
            self.assertFalse(pane._modulebar.fold.isVisibleTo(pane._modulebar))   # pas de bouton dans la barre
            pane._module_tab.clicked.emit()                      # repliee : barre cachee, titre au bord
            self.assertFalse(pane._modulebar.isVisible())
            self.assertLess(pane.title_area().x(), 40)
            pane.apply_settings(dict(pane._settings, board_modulebar_fold_style="narrow"))
            self.assertTrue(pane._modulebar.isVisible())         # meme etat replie : barre etroite
            self.assertTrue(pane._modulebar.folded)
            self.assertFalse(pane._module_tab.isVisible())
            pane.set_modulebar_folded(False)


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
        manager = self.pane._miro_bars.manager
        self.assertTrue(manager.dynamic["ctx"])                           # la selection est refaite : ses boutons sont la
        self.assertTrue(all(manager.widgets[key].isVisible() for key in manager.dynamic["ctx"]))
        self.assertGreater(self.pane._contextbar.width(), 300)            # plus de barre de 12 x 12 px
        QTest.keyClicks(viewport, " !")
        count = self.scene.undo.count()
        QTest.mouseClick(viewport, Qt.LeftButton, pos=self.view.mapFromScene(QPointF(900, 700)))
        settle(0.05)
        self.assertFalse(shape.text_item.editing())
        self.assertEqual(self.scene.undo.count(), count + 1)
        self.scene.undo.undo()
        self.assertEqual(self.scene.item(shape.item_id).data["text"], "Forme")


class ImageZoom100Test(_PaneCase):
    """Clic droit sur une image : « Zoom 100 % sur cette image » (demande de l'utilisateur, 2026-11-03)."""

    def test_the_board_zooms_so_that_one_image_pixel_is_one_screen_pixel(self):
        path = self.dir / "photo.png"
        image = QImage(1600, 1200, QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        image.save(str(path))
        self.assertTrue(self.view.add_image_files([path], QPointF(0, 0)))
        item = next(i for i in self.scene.board_items() if i.kind == "image")
        self.assertEqual(item.content_rect().width(), 600.0)          # posée réduite à 600 unités
        self.assertTrue(self.view.zoom_100_on(item))
        ratio = self.view.devicePixelRatioF() or 1.0
        on_screen = self.view.mapFromScene(item.mapToScene(item.content_rect()).boundingRect()).boundingRect()
        self.assertAlmostEqual(self.view.zoom(), 1600 / 600 / ratio, places=3)
        self.assertAlmostEqual(on_screen.width() * ratio, 1600, delta=3)
        center = self.view.mapFromScene(item.mapToScene(item.content_rect().center()))
        self.assertLess((center - self.view.viewport().rect().center()).manhattanLength(), 3)


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


class LegacyMroPaneTest(_PaneCase):
    def test_old_mro_opens_then_saves_as_brd(self):
        """Ancien `.mro` (demande de l'utilisateur 2026-11-05) : ouvert tel quel, puis enregistre en `.brd` (renomme ;
        ses images, dans `<nom>_assets`, restent valables)."""
        old = self.dir / "ancien.mro"
        data = model.empty_board()
        data["items"].append(model.new_item("sticky", text="garde"))
        serialization.save(old, data)
        self.assertTrue(self.pane.open(old))
        self.pane._set_dirty(True)                                       # modifie : l'enregistrement ecrit
        self.assertTrue(self.pane.save())
        new = self.dir / "ancien.brd"
        self.assertEqual(self.pane.path, new)
        self.assertFalse(old.exists())
        self.assertIn("garde", [d.get("text") for d in serialization.load(new)["items"]])


class MroIconsTest(_PaneCase):
    def test_icon_rows_and_provider(self):
        import settings_window_v2 as v2
        keys = {spec.params["ui_key"] for spec in v2.CATALOG["MRO : Icones"]}
        self.assertIn("ui_board_select", keys)
        self.assertIn("ui_board_lock", keys)
        self.assertNotIn("ui_board_design_present", keys)                # chaque module a SA section « Icônes »
        self.assertIn(("Icônes", "MRO : Icones"), [(n.title, n.group) for n in v2.MRO_TREE])
        bar = "Board : Barre de sélection : Icônes"            # toute la barre des modules (demande du 2026-11-13)
        sel = next(n for n in v2.BOARD_TREE if n.title == "Barre de sélection")
        self.assertIn(("Icônes", bar), [(n.title, n.group) for n in sel.children])
        bar_keys = [spec.params["ui_key"] for spec in v2.CATALOG[bar] if spec.kind == "ui_icon"]
        for module in ("miro", "cad", "design", "tableur", "illustrator", "photoshop", "pdf"):
            self.assertIn(f"ui_board_{module}", bar_keys)
        self.assertIn("ui_board_solo", bar_keys)
        self.assertNotIn("Icônes", [n.title for n in v2.BOARD_TREE])
        self.assertNotIn("Icônes", [n.title for n in v2.TABLEUR_TREE] + [n.title for n in v2.PS_TREE])
        self.assertIn(bar, v2.ICON_GROUPS)
        for tree, group, key in ((v2.DESIGN_TREE, "Design : Icônes", "ui_board_design_present"),
                                 (v2.ILL_TREE, "Illustrator : Icônes", "ui_board_ill_pen")):
            self.assertIn(("Icônes", group), [(n.title, n.group) for n in tree])
            self.assertIn(key, {spec.params["ui_key"] for spec in v2.CATALOG[group]})
            self.assertIn(group, v2.ICON_GROUPS)
        every = [spec.params["ui_key"] for g in __import__("fm_board.settings", fromlist=["x"]).ICON_GROUPS_BY_MODULE for spec in v2.CATALOG[g]
                 if spec.kind == "ui_icon"]
        self.assertEqual(len(every), len(set(every)))                    # aucune icone dans deux sections
        self.assertEqual(set(every), {f"ui_board_{kind}" for kind, _label in model.ICON_ROWS})
        # Ouverture, Navigation, Grille : onglet Board (venues de MRO)
        for title in ("Ouverture", "Navigation", "Grille"):
            self.assertIn((title, f"Board : {title}"), [(n.title, n.group) for n in v2.BOARD_TREE])
            self.assertNotIn(title, [n.title for n in v2.MRO_TREE])
        self.assertIn((v2.MRO_TAB, None), v2.MODULE_SCOPES["board"])
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
        """Les barres flottantes de Miro suivent la section « Palette » de fm_theme (`palette_*`), en direct."""
        from fm_theme import palette as fm_palette
        bar = self.pane._toolbar
        self.assertEqual(bar.size(), bar.grid_size())
        before = bar.width()
        sides = {"top": False, "right": False, "bottom": False, "left": False}
        self.pane.apply_settings({"palette_bg_color": "#ff0000", "palette_cell_size": 48, "palette_border_enabled": sides})
        self.assertEqual(fm_palette.LOOK["bg"], "#ff0000")
        self.assertGreater(bar.width(), before)                           # cases plus grandes : la barre grandit
        self.assertEqual(bar.size(), bar.grid_size())
        self.assertEqual(self.pane._tool_buttons["hand"].width(), 48)
        image = bar.grab().toImage()
        self.assertEqual(QColor(image.pixel(2, bar.height() // 2)).name(), "#ff0000")
        self.pane.apply_settings({})
        self.assertEqual(bar.width(), before)

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

    def test_negative_setting_asks_the_app_to_save(self):
        """Reglage « Icones et textes en negatif » (cartouche, barres du CAD) : applique tout de suite puis enregistre. Il n'y a
        plus de bouton dans les barres de Miro : leur aspect est celui de fm_theme."""
        written = []
        old = board_ui.SETTING_WRITER
        board_ui.SETTING_WRITER = lambda key, value: written.append((key, value))
        try:
            self.assertNotIn("invert", self.pane._miro_bars.manager.widgets)
            self.pane.toggle_invert()
            self.assertTrue(self.pane.toolbar_style["invert"])
            self.pane.toggle_invert()
            self.assertFalse(self.pane.toolbar_style["invert"])
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
        self.pane.apply_settings({"board_toolbar_invert": True})
        self.assertTrue(self.pane.toolbar_style["invert"])                # cartouche et barres du CAD
        self.pane.apply_settings({"board_toolbar_invert": False})
        self.assertFalse(self.pane.toolbar_style["invert"])
        import settings_store
        self.assertIn("board_toolbar_invert", settings_store.DEFAULT_SETTINGS)


class MiroFloatingBarsTest(_PaneCase):
    """Barres flottantes de Miro (fm_board/bars.py + fm_theme/bar_manager.py, maquette Claude Design « Barres d'outils
    flottantes ») : elles remplacent les anciennes barres d'outils de Miro ; la barre des modules n'est pas touchée."""

    def manager(self):
        return self.pane._miro_bars.manager

    def drag_out(self, key, x=700, y=300):
        """Ctrl + glisser (méthodes du gestionnaire) : l'élément `key` lâché dans le vide du board."""
        from PySide6.QtCore import QPoint
        mgr = self.manager()
        bar = mgr.bar_of(key)
        item = bar._items[key]
        mgr.begin_item_drag(bar, item, bar.mapToGlobal(item.widget.geometry().center()))
        mgr.item_drag_to(self.pane.mapToGlobal(QPoint(x, y)))
        mgr.end_item_drag()

    def test_default_layout_puts_every_tool_in_a_named_bar(self):
        mgr = self.manager()
        self.assertEqual([b.title() for b in mgr.bars], ["Outils", "Créer", "Page", "Vue", "Dessin", "Sélection"])
        self.assertEqual(sorted(mgr.bar("b1").keys()), ["hand", "select"])
        self.assertEqual(sorted(mgr.bar("b2").keys()),
                         sorted(["sticky", "text", "shape", "connector", "draw", "comment", "frame", "image"]))
        self.assertEqual(sorted(mgr.bar("b4").keys()), ["fit", "zoom", "zoom_in", "zoom_out"])
        every_tool = {kind for kind, _tip in board_ui.TOOLS}
        self.assertTrue(every_tool <= set(mgr.widgets))                     # aucun outil n'est perdu

    def test_the_module_bar_is_not_touched_and_the_bars_start_to_its_right(self):
        pane = self.pane
        self.assertTrue(pane._modulebar.isVisible())
        self.assertEqual(pane._modulebar.geometry().left(), 0)
        for bar in self.manager().bars:
            if bar.dock == "left":
                self.assertEqual(bar.x(), pane.left_edge())                  # clipsées au bord de la zone, pas sous la barre des modules
        self.assertEqual(self.manager().bar("b4").geometry().right() + 1, pane.width())     # « Vue » : à droite

    def test_the_module_bar_toggles_the_grid_and_sets_the_view_background(self):
        from fm_board import model, ui
        pane = self.pane
        bar = pane._modulebar
        foot = [bar.grid, bar.background, bar.reset]
        self.assertEqual(sorted(foot, key=lambda w: w.mapTo(bar, w.rect().topLeft()).y()), foot)   # au-dessus de « réinitialiser »
        on = bool(pane.scene.page.get("grid", True))
        bar.grid.click()
        self.assertEqual(bool(pane.scene.page.get("grid", True)), not on)
        self.assertEqual(bar.grid._on, not on)                               # l'icône suit la grille
        labels = [label for label, _c in ui.VIEW_BACKGROUNDS]
        self.assertEqual(labels, ["AutoCAD (sombre)", "Miro"])
        pane._open_background_menu(bar.background)
        menu = next(m for m in pane.findChildren(QMenu) if m.isVisible())
        next(a for a in menu.actions() if a.text().startswith("AutoCAD")).trigger()
        self.assertEqual(pane.scene.page.get("background"), "#212830")
        menu.close()
        pane._open_background_menu(bar.background)
        menu = next(m for m in pane.findChildren(QMenu) if m.isVisible())
        next(a for a in menu.actions() if a.text().startswith("Miro")).trigger()
        self.assertIsNone(pane.scene.page.get("background"))                 # couleur Miro = celle par défaut
        self.assertEqual(model.MIRO_BACKGROUND, "#f2f2f2")
        menu.close()

    def test_the_module_bar_keeps_one_width_and_a_long_press_shows_its_buttons(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        from fm_board import modulebar
        pane = self.pane
        bar = pane._modulebar
        width = bar.width()
        row = bar.rows["cad"]
        self.assertFalse(row.vis.isVisible())                                # icônes seules
        self.assertEqual(pane.left_edge(), bar.geometry().right() + 1)       # barres collées contre elle
        with mock.patch.dict(modulebar.LOOK, {"long_press": 150}):
            QTest.mousePress(row.icon, Qt.LeftButton, Qt.NoModifier, row.icon.rect().center())
            settle(0.3)
            flyout = bar._flyout
            self.assertTrue(flyout.isVisible())
            self.assertIs(row.vis.parentWidget(), flyout)                    # ses boutons, dans le volet
            QTest.mouseRelease(row.icon, Qt.LeftButton, Qt.NoModifier, row.icon.rect().center())
        self.assertEqual(bar.width(), width)                                 # même largeur
        flyout.hide()
        self.assertIs(row.vis.parentWidget(), row)
        self.assertFalse(row.vis.isVisible())

    def test_one_module_flyout_closes_after_a_choice_and_ctrl_opens_every_module(self):
        """Demande de l'utilisateur, 2026-11-04 : volet d'UN module refermé des que le choix est fait ; Ctrl + appui
        long = les boutons de TOUS les modules, chacun en face de sa ligne, ouverts jusqu'a un clic ailleurs."""
        from PySide6.QtTest import QTest
        from fm_board import modulebar
        bar = self.pane._modulebar
        row = bar.rows["cad"]
        looks = []
        bar.lookToggled.connect(lambda name, kind: looks.append((name, kind)))
        with mock.patch.dict(modulebar.LOOK, {"long_press": 150}):
            QTest.mousePress(row.icon, Qt.LeftButton, Qt.NoModifier, row.icon.rect().center())
            settle(0.3)
            QTest.mouseRelease(row.icon, Qt.LeftButton, Qt.NoModifier, row.icon.rect().center())
            flyout = bar._flyout
            self.assertTrue(flyout.isVisible() and flyout.single())
            row.dim.click()
            self.assertEqual(looks, [("cad", "fade")])
            self.assertFalse(flyout.isVisible())                                  # choix fait : refermé
            self.assertIs(row.dim.parentWidget(), row)
            with mock.patch.object(modulebar.QApplication, "keyboardModifiers", return_value=Qt.ControlModifier):
                QTest.mousePress(row.icon, Qt.LeftButton, Qt.ControlModifier, row.icon.rect().center())
                settle(0.3)
                QTest.mouseRelease(row.icon, Qt.LeftButton, Qt.ControlModifier, row.icon.rect().center())
        self.assertTrue(flyout.isVisible())
        self.assertFalse(flyout.single())
        for other in bar.rows.values():                                          # tous, en face de leur ligne
            self.assertIs(other.vis.parentWidget(), flyout)
            self.assertTrue(other.vis.isVisible())
            centre = other.mapToGlobal(other.rect().center()).y()
            self.assertLessEqual(abs(other.vis.mapToGlobal(other.vis.rect().center()).y() - centre), 2)
        names = list(bar.rows)
        bar.rows[names[0]].vis.click()
        bar.rows[names[1]].solo.click()
        self.assertTrue(flyout.isVisible())                                      # reste ouvert pour tout régler
        self.assertEqual(looks[1:], [(names[0], "hide"), (names[1], "solo")])
        flyout.hide()                                                            # (clic ailleurs : fenêtre popup)
        self.assertTrue(all(r.vis.parentWidget() is r and not r.vis.isVisible() for r in bar.rows.values()))

    def test_long_press_then_release_on_a_button_chooses_it(self):
        """Demande de l'utilisateur, 2026-11-05 : appui long, glisser sur « griser » SANS relacher, relacher = choisi."""
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtTest import QTest
        from fm_board import modulebar
        bar = self.pane._modulebar
        row = bar.rows["cad"]
        looks = []
        bar.lookToggled.connect(lambda name, kind: looks.append((name, kind)))
        with mock.patch.dict(modulebar.LOOK, {"long_press": 150}):
            QTest.mousePress(row.icon, Qt.LeftButton, Qt.NoModifier, row.icon.rect().center())
            settle(0.3)
        flyout = bar._flyout
        self.assertTrue(flyout.isVisible())
        flyout.armed = True                                                       # bouton toujours tenu
        target = row.dim.mapToGlobal(row.dim.rect().center())
        local = QPointF(row.icon.mapFromGlobal(target))

        def send(kind, buttons):
            QApplication.sendEvent(row.icon, QMouseEvent(kind, local, QPointF(target), Qt.LeftButton, buttons,
                                                         Qt.NoModifier))
        send(QEvent.MouseMove, Qt.LeftButton)
        self.assertTrue(row.dim.isDown())                                         # survol : montre enfonce
        self.assertEqual(looks, [])
        send(QEvent.MouseButtonRelease, Qt.NoButton)
        self.assertEqual(looks, [("cad", "fade")])                                # applique au relachement
        self.assertFalse(flyout.isVisible())

    def test_isolating_a_module_makes_it_active(self):
        """Demande de l'utilisateur, 2026-11-05 : isoler un module inactif l'active."""
        pane = self.pane
        pane.set_module(None)
        pane.toggle_module_look("cad", "solo")
        self.assertTrue(pane.scene.module_state["cad"]["solo"])
        self.assertEqual(pane.module, "cad")
        pane.toggle_module_look("cad", "solo")                                    # sortie d'isolation : reste actif
        self.assertEqual(pane.module, "cad")

    def test_drawing_bar_and_presets_only_while_a_drawing_tool_is_chosen(self):
        pane = self.pane
        pane.view.set_tool("select")
        settle(0.05)
        self.assertFalse(pane._drawbar.isVisible())
        pane.view.set_tool("pen")
        settle(0.05)
        self.assertTrue(pane._drawbar.isVisible())
        self.assertTrue(all(button.isVisible() for button in pane._preset_buttons))
        self.assertTrue(pane._draw_buttons["pen"].active)
        pane.view.set_tool("sticky")
        settle(0.05)
        self.assertFalse(pane._drawbar.isVisible())

    def test_zoom_text_follows_the_view_and_a_tool_click_still_works(self):
        pane = self.pane
        pane.view.set_zoom(2.0)
        settle(0.05)
        self.assertEqual(pane._zoom_label.grab().isNull(), False)
        self.assertEqual(pane._zoom_label.text_value(), board_ui.format_zoom(pane.view.zoom()))
        pane._tool_buttons["hand"].click()
        self.assertEqual(pane.view.tool, "hand")
        self.assertTrue(pane._tool_buttons["hand"].active)

    def test_a_tool_dropped_in_the_void_becomes_a_bar_that_is_saved_and_restored(self):
        self.drag_out("sticky")
        mgr = self.manager()
        new = mgr.bar_of("sticky")
        self.assertNotEqual(new.bar_id, "b2")
        self.assertEqual(new.keys(), ["sticky"])
        self.assertNotIn("sticky", mgr.bar("b2").keys())
        saved = self.pane._settings["board_bars"]["miro"]
        self.assertIn("sticky", next(b for b in saved["bars"] if b["id"] == new.bar_id)["items"])
        other = BoardPane(self.host, {"board_bars": self.pane._settings["board_bars"]})   # autre ouverture : meme disposition
        other.open(self.path)
        other.fit()
        other.show()
        settle(0.05)
        self.assertEqual(other._miro_bars.manager.bar_of("sticky").bar_id, new.bar_id)
        self.assertEqual(other._miro_bars.manager.bar_of("sticky").keys(), ["sticky"])

    def test_the_selection_buttons_keep_the_cell_the_user_gave_them(self):
        note = self.scene.add_new(model.new_item("sticky", text="x"))
        note.setSelected(True)
        settle(0.05)
        mgr = self.manager()
        self.assertEqual(mgr.bar_of("link").bar_id, "b6")                    # par defaut : barre « Selection »
        self.drag_out("link", 650, 400)
        moved = mgr.bar_of("link").bar_id
        self.assertNotEqual(moved, "b6")
        note.setSelected(False)
        settle(0.05)
        self.assertFalse(mgr.dynamic["ctx"])
        note.setSelected(True)
        settle(0.05)
        self.assertEqual(mgr.bar_of("link").bar_id, moved)                   # boutons refaits : « Lien » retrouve sa barre

    def test_a_removed_old_toolbar_attribute_still_answers_for_other_modules(self):
        """CAD et Design placent leurs barres d'apres `_zoombar` : la barre « Vue » les renseigne."""
        pane = self.pane
        self.assertIs(pane._zoombar, self.manager().bar("b4"))
        self.assertTrue(pane._zoombar.isVisible())
        self.assertGreater(pane._zoombar.width(), 100)

    def test_reset_returns_to_the_default_layout(self):
        self.drag_out("sticky")
        self.pane._miro_bars.reset()
        self.assertEqual(self.manager().bar_of("sticky").bar_id, "b2")
        self.assertEqual(len(self.manager().bars), 6)


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
        self.assertEqual(path, self.root / "set" / "Atelier.brd")
        settle(0.3)
        self.assertTrue(win.btn_board.isEnabled())
        win.on_activated(path)
        settle(0.3)
        pane = win._board
        self.assertIsNotNone(pane)
        self.assertEqual(pane.geometry(), win.scroll.viewport().rect())
        # Fluidite : colonnes cachees sous le board (fondu fini), remontrees a la fermeture.
        settle(0.5)
        self.assertFalse(win.columns_host.isVisible())
        group = win.titlebar.board_group()
        self.assertTrue(group.isVisible())
        from settings_store import load_settings
        settings = load_settings()
        settings["board_snap_distance"] = 12
        win._apply_settings(settings, {"board_snap_distance"})
        self.assertEqual(pane.scene.snap["distance"], 12)                 # Reglages > MRO en direct
        badge = win._board_render_badge                                   # encart accroche en bas de la barre
        self.assertTrue(badge.isVisible() and badge.hanging)
        self.assertEqual(badge.geometry().bottom(), win.titlebar.height() - 1)
        self.assertFalse(pane._badge.isVisible())
        self.assertEqual(win.status_right.text(), "enregistré")           # a la place de « read-only »
        pane.scene.add_new(model.new_item("sticky", text="idée"))
        settle(0.05)
        self.assertEqual(win.status_right.text(), "modifié")
        self.assertNotIn("Atelier", win.status_right.text())
        if __import__("os").environ.get("BOARD_SHOT"):
            win.grab().save(__import__("os").environ["BOARD_SHOT"])
        self.assertTrue(win._close_board())
        settle(0.3)
        self.assertIsNone(win._board)
        self.assertTrue(win.columns_host.isVisible())
        self.assertEqual(win.status_right.text(), "read-only")
        self.assertFalse(badge.isVisible())
        self.assertEqual(serialization.load(path)["items"][0]["text"], "idée")

    def test_double_click_on_a_dxf_opens_it_in_the_board(self):
        import ezdxf
        win = self.win
        source = self.root / "set" / "plan.dxf"
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (40, 0))
        doc.saveas(source)
        before = source.read_bytes()
        with mock.patch("main_window.viewer.open_path", side_effect=AssertionError("logiciel externe ouvert")):
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
