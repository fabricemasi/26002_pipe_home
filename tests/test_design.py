"""Module Design du board (paquet fm_design/, à la manière de Canva) : modèle et compatibilité du .mro, géométrie
pure, pages (ajout, duplication, suppression, ordre, redimensionnement), éléments (formes, textes, images), gestes à
la souris (sélection, Ctrl + glisser = déplacer, glisser sans Ctrl = cadre de sélection, poignées, rotation,
recadrage), clavier, groupes, alignement, calques, modèles, export (PNG, JPEG, PDF, SVG), sauvegarde et réouverture."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

APP = QApplication.instance() or QApplication([])

from fm_board import model, serialization
from fm_board import ui as board_ui
from fm_design import design_model as dm, document as doc, geometry, render, templates
from fm_design.items import DesignImageItem, DesignPageItem, DesignShapeItem, DesignTextItem

_PANES = []


def settle(seconds=0.05):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        APP.processEvents()
        time.sleep(0.003)


class DesignTestCase(unittest.TestCase):
    """Board ouvert sur un .mro temporaire, module Design actif."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="design_test_"))
        self.path = serialization.create_board_file(self.tmp / "essai.mro")
        self.host = QWidget()
        self.host.resize(1400, 900)
        self.pane = board_ui.BoardPane(self.host)
        _PANES.append(self.pane)
        self.assertTrue(self.pane.open(self.path))
        self.pane.resize(1400, 900)
        self.host.show()
        self.pane.show()
        self.pane.set_module("design")
        self.ctl = self.pane.design
        self.scene = self.pane.scene
        self.view = self.pane.view
        settle()

    def tearDown(self):
        from PySide6.QtCore import QCoreApplication
        for pane in _PANES:
            try:
                pane._autosave.stop()
                pane.deleteLater()
            except RuntimeError:
                pass
        _PANES.clear()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- aides --
    def page(self, w=1000.0, h=800.0):
        page = doc.add_page(self.scene, w, h, origin=QPointF(0, 0))
        self.ctl.set_current_page(page)
        self.view.set_zoom(0.5)
        self.view.center_on(page.mapRectToScene(page.content_rect()).center())
        settle()
        return page

    def mouse(self, kind, scene_pt, button=Qt.LeftButton, buttons=None, mods=Qt.NoModifier):
        pos = QPointF(self.view.mapFromScene(scene_pt))
        if buttons is None:
            buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else button
        event = QMouseEvent(kind, pos, QPointF(self.view.viewport().mapToGlobal(pos.toPoint())), button, buttons,
                            mods)
        QApplication.sendEvent(self.view.viewport(), event)

    def drag(self, start, end, mods=Qt.NoModifier, steps=4):
        self.mouse(QEvent.MouseButtonPress, start, mods=mods)
        for n in range(1, steps + 1):
            p = start + (end - start) * (n / steps)
            self.mouse(QEvent.MouseMove, p, buttons=Qt.LeftButton, mods=mods)
        self.mouse(QEvent.MouseButtonRelease, end, mods=mods)
        settle()

    def key(self, key, mods=Qt.NoModifier, text=""):
        QApplication.sendEvent(self.view, QKeyEvent(QEvent.KeyPress, key, mods, text))
        settle()

    def center(self, item):
        return item.mapToScene(item.content_rect().center())


class ModelTest(unittest.TestCase):
    def test_design_types_are_known_and_normalized(self):
        raw = {"id": "a", "type": "design_shape", "w": -5, "opacity": 7, "shadow": {"blur": 3},
               "future_field": 1}
        item = model.normalize_item(raw)
        self.assertEqual(item["w"], dm.MIN_SIZE)
        self.assertEqual(item["opacity"], 1.0)
        self.assertEqual(item["shadow"]["blur"], 3.0)
        self.assertFalse(item["shadow"]["enabled"])
        self.assertEqual(item["future_field"], 1)          # champ inconnu gardé
        image = model.normalize_item({"id": "b", "type": "design_image", "crop": [0.8, 0, 0.2, 1]})
        self.assertEqual(image["crop"], [0.0, 0.0, 1.0, 1.0])

    def test_unknown_type_from_newer_version_kept(self):
        board = model.normalize({"items": [{"id": "x", "type": "design_video", "a": 1}], "page": {}})
        self.assertEqual(board["foreign"], [{"id": "x", "type": "design_video", "a": 1}])

    def test_layout_positions_stack_pages(self):
        pos = dm.layout_positions([(100, 50), (200, 80)], (0, 0), gap=10)
        self.assertEqual(pos, [(0.0, 0.0), (-50.0, 60.0)])


class GeometryTest(unittest.TestCase):
    def test_snap_move_to_page_center(self):
        dx, dy, guides = geometry.snap_move((397, 10, 200, 100), [], (1000, 800), 5)
        self.assertEqual(dx, 3)
        self.assertIn(("v", 500.0), guides)

    def test_align_and_distribute(self):
        rects = [(0, 0, 10, 10), (50, 20, 10, 10), (200, 5, 10, 10)]
        self.assertEqual([p[0] for p in geometry.align(rects, "left")], [0, 0, 0])
        self.assertEqual([p[1] for p in geometry.align(rects, "bottom")], [20, 20, 20])
        self.assertEqual([p[0] for p in geometry.distribute(rects, "h")], [0, 100, 200])

    def test_crop_edge_keeps_scale_and_bounds(self):
        crop, applied = geometry.crop_edge([0.0, 0.0, 1.0, 1.0], (200, 100), "l", 50)
        self.assertAlmostEqual(crop[0], 0.25)
        self.assertAlmostEqual(applied, 50)
        crop, applied = geometry.crop_edge([0.25, 0.0, 1.0, 1.0], (150, 100), "l", -500)
        self.assertEqual(crop[0], 0.0)                       # borné par l'image source
        self.assertAlmostEqual(applied, -50)
        self.assertEqual(geometry.pan_crop([0.25, 0, 0.75, 1], (100, 100), 1000, 0)[0], 0.0)


class VerticalSliceTest(DesignTestCase):
    """Page -> rectangle -> sélection -> poignée -> Ctrl + glisser -> sauvegarde -> réouverture."""

    def test_rectangle_end_to_end(self):
        page = self.page()
        rect = self.ctl.add_shape("rect", {"x": 100.0, "y": 100.0, "w": 200.0, "h": 100.0, "fill": "#ff0000"})
        self.assertIs(rect.parentItem(), page)
        self.assertEqual(self.ctl.selection(), [rect])
        # Glisser SANS Ctrl : cadre de sélection, l'élément ne bouge pas (règle de l'appli).
        start = self.center(rect)
        self.drag(start, start + QPointF(150, 80))
        self.assertEqual(rect.pos(), QPointF(100, 100))
        # Ctrl + glisser : déplacement (Alt : sans magnétisme).
        self.ctl._select([rect])
        self.drag(start, start + QPointF(60, 40), mods=Qt.ControlModifier | Qt.AltModifier)
        # Ctrl + Alt = copie déplacée : l'original reste, la copie est choisie.
        copies = self.ctl.selection()
        self.assertEqual(len(copies), 1)
        self.assertIsNot(copies[0], rect)
        self.assertEqual(copies[0].pos(), QPointF(160, 140))
        self.scene.undo.undo()                               # la copie part avec son déplacement ? (2 étapes)
        self.scene.undo.undo()
        self.ctl._select([rect])
        self.drag(start, start + QPointF(60, 40), mods=Qt.ControlModifier)
        self.assertAlmostEqual(rect.pos().x(), 160, delta=0.01)
        self.assertAlmostEqual(rect.pos().y(), 140, delta=0.01)
        # Poignée du coin bas droit : proportions gardées.
        corner = rect.mapToScene(rect.content_rect().bottomRight())
        self.drag(corner, corner + QPointF(100, 0))
        self.assertAlmostEqual(rect.size()[0], 300, delta=0.5)
        self.assertAlmostEqual(rect.size()[1], 150, delta=0.5)
        self.assertAlmostEqual(rect.pos().x(), 160, delta=0.5)     # coin opposé fixe
        # Sauvegarde, réouverture : propriétés et place identiques.
        self.assertTrue(self.pane.save())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        saved = [i for i in data["items"] if i["type"] == "design_shape"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["page"], page.item_id)
        other = board_ui.BoardPane(self.host)
        _PANES.append(other)
        self.assertTrue(other.open(self.path))
        again = other.scene.item(rect.item_id)
        self.assertIsInstance(again, DesignShapeItem)
        self.assertIsInstance(again.parentItem(), DesignPageItem)
        self.assertEqual(again.to_dict(), rect.to_dict())

    def test_plain_click_selects_shift_click_adds(self):
        self.page()
        a = self.ctl.add_shape("rect", {"x": 50.0, "y": 50.0, "w": 100.0, "h": 100.0})
        b = self.ctl.add_shape("ellipse", {"x": 400.0, "y": 50.0, "w": 100.0, "h": 100.0})
        self.scene.clearSelection()
        self.mouse(QEvent.MouseButtonPress, self.center(a))
        self.mouse(QEvent.MouseButtonRelease, self.center(a))
        self.assertEqual(self.ctl.selection(), [a])
        self.mouse(QEvent.MouseButtonPress, self.center(b), mods=Qt.ShiftModifier)
        self.mouse(QEvent.MouseButtonRelease, self.center(b), mods=Qt.ShiftModifier)
        self.assertEqual(set(self.ctl.selection()), {a, b})
        # Cadre de sélection depuis le vide de la page
        page = a.page_item()
        self.scene.clearSelection()
        self.drag(page.mapToScene(QPointF(10, 10)), page.mapToScene(QPointF(600, 300)))
        self.assertEqual(set(self.ctl.selection()), {a, b})


class GestureTest(DesignTestCase):
    def test_move_snaps_to_page_center_and_drops_on_other_page(self):
        page = self.page()
        item = self.ctl.add_shape("rect", {"x": 100.0, "y": 100.0, "w": 200.0, "h": 100.0})
        start = self.center(item)
        # centre de la page en x = 500 ; centre de l'élément = 200 -> +297 : aimanté à +300
        self.drag(start, start + QPointF(297, 0), mods=Qt.ControlModifier)
        self.assertAlmostEqual(item.pos().x(), 400, delta=0.01)
        second = doc.add_page(self.scene, 1000, 800, after=page)
        self.ctl._select([item])
        target = self.center(second)
        self.drag(self.center(item), target, mods=Qt.ControlModifier | Qt.AltModifier, steps=2)
        moved = self.ctl.selection()[0]
        self.assertIs(moved.page_item(), second)
        self.assertEqual(moved.data["page"], second.item_id)

    def test_rotation_handle_and_multi_resize(self):
        self.page()
        a = self.ctl.add_shape("rect", {"x": 100.0, "y": 100.0, "w": 100.0, "h": 100.0})
        handles = dict((n, p) for n, p, _a in self.ctl.handles())
        c = self.center(a)
        rot = handles["rot"]
        # le pointeur passe du dessous (90°) à la droite (0°) du centre : -90°
        self.drag(rot, QPointF(c.x() + 200, c.y()), steps=3)
        self.assertAlmostEqual(a.rotation(), -90, delta=0.01)
        self.scene.undo.undo()
        self.assertAlmostEqual(a.rotation(), 0, delta=0.01)
        b = self.ctl.add_shape("rect", {"x": 300.0, "y": 100.0, "w": 100.0, "h": 50.0})
        self.ctl._select([a, b])
        handles = dict((n, p) for n, p, _a in self.ctl.handles())
        self.assertNotIn("l", handles)                     # sélection multiple : coins seulement
        self.drag(handles["br"], handles["br"] + QPointF(300, 0))
        self.assertAlmostEqual(a.size()[0], 200, delta=0.5)
        self.assertAlmostEqual(b.size()[0], 200, delta=0.5)
        self.assertAlmostEqual(b.pos().x(), 500, delta=0.5)

    def test_text_corner_scales_font_side_changes_width(self):
        self.page()
        text = self.ctl.add_text("body", {"x": 100.0, "y": 100.0, "w": 400.0, "text": "Bonjour"}, edit=False)
        size0 = text.data["font_size"]
        handles = dict((n, p) for n, p, _a in self.ctl.handles())
        self.assertNotIn("t", handles)
        self.drag(handles["br"], handles["br"] + QPointF(400, 0))
        self.assertAlmostEqual(text.data["font_size"], size0 * 2, delta=0.2)
        handles = dict((n, p) for n, p, _a in self.ctl.handles())
        self.drag(handles["r"], handles["r"] - QPointF(300, 0))
        self.assertAlmostEqual(text.size()[0], 500, delta=0.5)
        self.assertAlmostEqual(text.data["font_size"], size0 * 2, delta=0.2)

    def test_image_side_handle_crops_without_distortion(self):
        page = self.page()
        source = self.tmp / "photo.png"
        image = QImage(200, 100, QImage.Format_RGB32)
        image.fill(QColor("#336699"))
        image.save(str(source))
        self.assertTrue(self.ctl.add_image_files([source]))
        item = self.ctl.selection()[0]
        self.assertIsInstance(item, DesignImageItem)
        self.assertIs(item.page_item(), page)
        w0, h0 = item.size()
        handles = dict((n, p) for n, p, _a in self.ctl.handles())
        self.drag(handles["l"], handles["l"] + QPointF(w0 / 4, 0))
        self.assertAlmostEqual(item.data["crop"][0], 0.25, delta=0.01)
        self.assertAlmostEqual(item.size()[0], w0 * 0.75, delta=0.5)
        self.assertAlmostEqual(item.size()[1], h0, delta=0.01)
        # Mode recadrage : Ctrl + glisser = l'image glisse dans son cadre.
        self.ctl.start_crop(item)
        c = self.center(item)
        self.drag(c, c + QPointF(w0 / 8, 0), mods=Qt.ControlModifier)
        self.assertLess(item.data["crop"][0], 0.25)
        self.key(Qt.Key_Return)
        self.assertIsNone(self.ctl.crop_item)


class KeyboardTest(DesignTestCase):
    def test_shortcuts(self):
        page = self.page()
        self.key(Qt.Key_R, text="r")
        rect = self.ctl.selection()[0]
        self.assertEqual(rect.data["shape"], "rect")
        self.assertEqual(self.pane.module, "design")          # la lettre n'active pas un outil de Miro
        x = rect.pos().x()
        self.key(Qt.Key_Right, Qt.ShiftModifier)
        self.assertEqual(rect.pos().x(), x + 10)
        self.key(Qt.Key_D, Qt.ControlModifier)
        self.assertEqual(len(doc.elements(self.scene, page)), 2)
        self.key(Qt.Key_A, Qt.ControlModifier)
        self.assertEqual(len(self.ctl.selection()), 2)
        self.key(Qt.Key_G, Qt.ControlModifier)
        groups = {i.data["group"] for i in self.ctl.selection()}
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups.pop())
        self.scene.clearSelection()
        self.mouse(QEvent.MouseButtonPress, self.center(rect))
        self.mouse(QEvent.MouseButtonRelease, self.center(rect))
        self.assertEqual(len(self.ctl.selection()), 2)        # un clic choisit tout le groupe
        self.key(Qt.Key_G, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual({i.data["group"] for i in self.ctl.selection()}, {""})
        self.key(Qt.Key_Delete)
        self.assertEqual(doc.elements(self.scene, page), [])
        self.scene.undo.undo()
        self.assertEqual(len(doc.elements(self.scene, page)), 2)

    def test_copy_paste_and_text_styles(self):
        page = self.page()
        text = self.ctl.add_text("heading", {"text": "Titre"}, edit=False)
        self.key(Qt.Key_B, Qt.ControlModifier)
        self.assertFalse(text.data["bold"])                    # le titre était gras
        self.key(Qt.Key_E, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(text.data["align"], "center")
        self.key(Qt.Key_C, Qt.ControlModifier)
        self.key(Qt.Key_V, Qt.ControlModifier)
        texts = [i for i in doc.elements(self.scene, page) if isinstance(i, DesignTextItem)]
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[1].pos(), texts[0].pos() + QPointF(20, 20))


class DocumentTest(DesignTestCase):
    def test_pages_add_duplicate_move_delete_undo(self):
        first = self.page(500, 400)
        self.ctl.add_shape("rect", {"x": 10.0, "y": 10.0})
        second = doc.add_page(self.scene, 500, 400, after=first)
        self.assertEqual(second.pos().y(), first.pos().y() + 400 + dm.PAGE_GAP)
        third = doc.duplicate_page(self.scene, first)
        self.assertEqual([p.item_id for p in doc.pages(self.scene)], [first.item_id, third.item_id, second.item_id])
        self.assertEqual(len(doc.elements(self.scene, third)), 1)
        doc.move_page(self.scene, second, 0)
        self.assertEqual(doc.pages(self.scene)[0], second)
        self.assertEqual(second.pos().y(), 0 - 200)            # origine de la 1re page gardée
        doc.delete_page(self.scene, third)
        self.assertNotIn(third, doc.pages(self.scene))
        self.assertEqual(len(doc.elements(self.scene)), 1)
        self.scene.undo.undo()
        third = [p for p in doc.pages(self.scene) if p.item_id == third.item_id][0]
        self.assertEqual(len(doc.elements(self.scene, third)), 1)
        self.assertIs(doc.elements(self.scene, third)[0].parentItem(), third)

    def test_delete_page_from_board_deletes_its_elements(self):
        page = self.page()
        self.ctl.add_shape("rect")
        self.scene.delete_items([page])                      # suppression par le board (module Miro)
        self.assertEqual(doc.elements(self.scene), [])
        self.scene.undo.undo()
        self.assertEqual(doc.elements(self.scene)[0].parentItem(), self.scene.item(page.item_id))

    def test_resize_page_scales_content(self):
        page = self.page(1000, 1000)
        item = self.ctl.add_shape("rect", {"x": 100.0, "y": 100.0, "w": 200.0, "h": 200.0, "stroke_width": 10.0})
        doc.resize_page(self.scene, page, 500, 1000, scale_content=True)
        self.assertEqual(page.size(), (500.0, 1000.0))
        self.assertAlmostEqual(item.size()[0], 100)
        self.assertAlmostEqual(item.data["stroke_width"], 5)
        self.assertAlmostEqual(item.pos().y(), 50 + 250)        # contenu centré verticalement

    def test_align_distribute_restack(self):
        page = self.page()
        items = [self.ctl.add_shape("rect", {"x": float(x), "y": float(y), "w": 50.0, "h": 50.0})
                 for x, y in ((0, 0), (100, 30), (400, 60))]
        doc.align_items(self.scene, items, "top", False)
        self.assertEqual({i.pos().y() for i in items}, {0.0})
        doc.align_items(self.scene, [items[0]], "right", False)    # un seul : sur la page
        self.assertEqual(items[0].pos().x(), page.size()[0] - 50)
        doc.distribute_items(self.scene, items, "h")
        xs = sorted(i.pos().x() for i in items)
        self.assertAlmostEqual(xs[1] - xs[0], xs[2] - xs[1])
        doc.restack(self.scene, [items[0]], "front")
        self.assertEqual(doc.elements(self.scene, page)[-1], items[0])
        doc.restack(self.scene, [items[0]], "backward")
        self.assertEqual(doc.elements(self.scene, page)[-2], items[0])

    def test_template_single_undo(self):
        page = self.page()
        undo_before = self.scene.undo.index()
        result = doc.apply_template(self.scene, templates.by_key("quote"), page=page)
        self.assertIs(result, page)
        self.assertEqual(page.size(), (1080.0, 1080.0))
        self.assertEqual(page.data["background"], "#111111")
        self.assertEqual(len(doc.elements(self.scene, page)), 4)
        self.assertEqual(self.scene.undo.index(), undo_before + 1)
        self.scene.undo.undo()
        self.assertEqual(doc.elements(self.scene, page), [])
        self.assertEqual(page.size(), (1000.0, 800.0))


class FileTest(DesignTestCase):
    def test_old_board_untouched_and_design_roundtrip(self):
        """Un board ancien (Miro seul) se relit et se réécrit sans perte ; un board avec Design se relit à
        l'identique."""
        old = {"format": "pipeline-board", "version": 2, "page": {"background": "#ffffff", "custom": 1},
               "view": {"zoom": 1.0, "center": [0, 0]}, "extra_key": {"keep": True},
               "items": [{"id": "s1", "type": "sticky", "x": 1, "y": 2, "w": 200, "h": 200, "text": "hé"},
                         {"id": "u1", "type": "mystery", "foo": [1, 2]}]}
        copy = self.tmp / "ancien.mro"
        copy.write_text(json.dumps(old), encoding="utf-8")
        other = board_ui.BoardPane(self.host)
        _PANES.append(other)
        self.assertTrue(other.open(copy))
        self.assertTrue(other.save())
        again = json.loads(copy.read_text(encoding="utf-8"))
        self.assertEqual(again["extra_key"], {"keep": True})
        self.assertEqual(again["page"]["custom"], 1)
        self.assertIn({"id": "u1", "type": "mystery", "foo": [1, 2]}, again["items"])
        self.assertEqual([i["text"] for i in again["items"] if i["type"] == "sticky"], ["hé"])
        # Design : tous les types, rechargés à l'identique
        page = self.page()
        doc.apply_template(self.scene, templates.by_key("event"), page=page)
        self.ctl.add_text("body", {"text": "Ligne 1\nLigne 2", "letter_spacing": 50.0, "line_height": 1.5},
                          edit=False)
        before = {i.item_id: i.to_dict() for i in doc.elements(self.scene) + doc.pages(self.scene)}
        self.assertTrue(self.pane.save())
        reopened = board_ui.BoardPane(self.host)
        _PANES.append(reopened)
        self.assertTrue(reopened.open(self.path))
        after = {i.item_id: i.to_dict() for i in doc.elements(reopened.scene) + doc.pages(reopened.scene)}
        self.assertEqual(before, after)


class ExportTest(DesignTestCase):
    def test_export_formats(self):
        page = self.page(400, 300)
        doc.change(self.scene, [page], lambda i: i.data.update(background="#00ff00"), "Fond")
        self.ctl.add_shape("rect", {"x": 0.0, "y": 0.0, "w": 200.0, "h": 300.0, "fill": "#ff0000"})
        second = doc.add_page(self.scene, 400, 300, after=page)
        png = render.export_pages([page], self.tmp / "out.png", "png", scale=0.5)
        image = QImage(str(png[0]))
        self.assertEqual((image.width(), image.height()), (200, 150))
        self.assertEqual(image.pixelColor(10, 10).name(), "#ff0000")
        self.assertEqual(image.pixelColor(190, 10).name(), "#00ff00")
        jpgs = render.export_pages([page, second], self.tmp / "out.jpg", "jpg")
        self.assertEqual([p.name for p in jpgs], ["out_p1.jpg", "out_p2.jpg"])
        pdf = render.export_pages([page, second], self.tmp / "out.pdf", "pdf")[0]
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))
        self.assertEqual(pdf.read_bytes().count(b"/Type /Page\n") + pdf.read_bytes().count(b"/Type /Page "), 2)
        svg = render.export_pages([page], self.tmp / "out.svg", "svg")[0]
        self.assertIn("<svg", svg.read_text(encoding="utf-8"))
        self.assertFalse(list(self.tmp.glob("*.part")))


class InterfaceTest(DesignTestCase):
    """Panneaux, barre contextuelle, miniatures, calques : construits et branchés (hors écran)."""

    def test_every_tab_and_context_bar_builds(self):
        page = self.page()
        for name, _g, _t in __import__("fm_design.ui", fromlist=["TABS"]).TABS:
            self.ctl.ui.set_tab(name)
            settle()
            self.assertTrue(self.ctl.ui.panel.isVisible())
        source = self.tmp / "p.png"
        QImage(40, 20, QImage.Format_RGB32).save(str(source))
        self.ctl.add_image_files([source])
        self.ctl.add_text("body", edit=False)
        self.ctl.add_shape("line")
        self.ctl.add_shape("star")
        for item in doc.elements(self.scene, page) + [None]:
            self.ctl._select([item] if item is not None else [])
            self.ctl.ui.sync()
            self.assertGreater(self.ctl.ui.context_layout.count(), 0)
            self.assertTrue(all(self.ctl.ui.context_layout.itemAt(n).widget().isVisibleTo(self.ctl.ui.context)
                                for n in range(self.ctl.ui.context_layout.count())))

    def test_thumbnails_redone_only_for_touched_pages(self):
        a = self.page()
        b = doc.add_page(self.scene, 500, 500, after=a)
        self.ctl.ui.rebuild_pages()
        item = self.ctl.add_shape("rect")
        self.ctl.ui.refresh_thumbs()
        with mock.patch.object(render, "thumbnail", wraps=render.thumbnail) as spy:
            doc.change(self.scene, [item], lambda i: i.data.update(fill="#000000"), "Fond")
            self.ctl.ui.refresh_thumbs()
        self.assertEqual(spy.call_count, 1)
        self.assertIs(spy.call_args[0][0], a)
        del b

    def test_layer_list_ctrl_drag_reorders(self):
        from fm_design.panels import LayerList
        page = self.page()
        items = [self.ctl.add_shape("rect", {"x": float(n * 50)}) for n in range(3)]
        layers = LayerList(self.ctl, None)
        layers.resize(250, 200)
        self.assertEqual(layers.items, list(reversed(items)))           # le plus haut d'abord
        row = LayerList.ROW
        press = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, row * 2.5), QPointF(), Qt.LeftButton, Qt.LeftButton,
                            Qt.NoModifier)
        with mock.patch("fm_design.panels.QApplication.keyboardModifiers", return_value=Qt.ControlModifier):
            layers.mousePressEvent(press)
        layers.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(20, 2), QPointF(), Qt.NoButton, Qt.LeftButton,
                                          Qt.ControlModifier))
        layers.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(20, 2), QPointF(), Qt.LeftButton,
                                             Qt.NoButton, Qt.ControlModifier))
        self.assertEqual(doc.elements(self.scene, page)[-1], items[0])   # l'ancien plus bas est en haut
        # sans Ctrl : un simple choix, l'ordre ne change pas
        before = doc.elements(self.scene, page)
        layers.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(20, row * 1.5), QPointF(), Qt.LeftButton,
                                           Qt.LeftButton, Qt.NoModifier))
        layers.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(20, 2), QPointF(), Qt.NoButton, Qt.LeftButton,
                                          Qt.NoModifier))
        layers.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(20, 2), QPointF(), Qt.LeftButton,
                                             Qt.NoButton, Qt.NoModifier))
        self.assertEqual(doc.elements(self.scene, page), before)
        layers.deleteLater()

    def test_parse_size(self):
        from fm_design.menus import parse_size
        self.assertEqual(parse_size("1200 x 628"), (1200.0, 628.0))
        self.assertEqual(parse_size("210×297 mm"), (round(210 * dm.MM, 2), round(297 * dm.MM, 2)))
        self.assertIsNone(parse_size("abc"))
        self.assertIsNone(parse_size("0 x 10"))


class TextAndImageTest(DesignTestCase):
    def test_double_click_edit_one_undo_step_and_empty_text_removed(self):
        self.page()
        text = self.ctl.add_text("body", {"text": "Avant"}, edit=False)
        index = self.scene.undo.index()
        pos = QPointF(self.view.mapFromScene(self.center(text)))
        QApplication.sendEvent(self.view.viewport(), QMouseEvent(QEvent.MouseButtonDblClick, pos, pos, Qt.LeftButton,
                                                                 Qt.LeftButton, Qt.NoModifier))
        self.assertTrue(self.ctl.text_editing())
        text.text_item.setPlainText("Après")
        self.view.finish_text_edit()
        settle()
        self.assertEqual(text.data["text"], "Après")
        self.assertEqual(self.scene.undo.index(), index + 1)
        self.ctl.edit_text(text)
        text.text_item.setPlainText("   ")
        self.view.finish_text_edit()
        settle(0.1)
        self.assertIsNone(self.scene.item(text.item_id))

    def test_text_layout_follows_style(self):
        self.page()
        text = self.ctl.add_text("body", {"text": "Un texte assez long pour passer à la ligne", "w": 200.0},
                                 edit=False)
        h1 = text.size()[1]
        doc.change(self.scene, [text], lambda i: i.data.update(line_height=2.0), "Interligne")
        self.assertGreater(text.size()[1], h1 * 1.4)
        doc.change(self.scene, [text], lambda i: i.data.update(w=900.0), "Largeur")
        self.assertLess(text.size()[1], h1)

    def test_image_adjustments_change_pixels(self):
        from fm_design.items import apply_adjustments
        image = QImage(4, 4, QImage.Format_ARGB32)
        image.fill(QColor(200, 50, 50))
        gray = apply_adjustments(image, 0, 0, 0, 0, True).pixelColor(1, 1)
        self.assertEqual(gray.red(), gray.green())
        bright = apply_adjustments(image, 50, 0, 0, 0, False).pixelColor(1, 1)
        self.assertGreater(bright.green(), 50)

    def test_shadow_and_gradient_render(self):
        page = self.page(200, 100)
        self.ctl.add_shape("rect", {"x": 0.0, "y": 0.0, "w": 200.0, "h": 100.0, "fill_type": "linear",
                                    "fill": "#000000", "fill2": "#ffffff", "gradient_angle": 0.0})
        image = render.render_image(page)
        self.assertLess(image.pixelColor(5, 50).lightness(), 30)
        self.assertGreater(image.pixelColor(195, 50).lightness(), 220)
        text = self.ctl.add_text("body", {"text": "Ombre", "shadow": {"enabled": True, "color": "#ff0000ff",
                                                                     "dx": 4.0, "dy": 4.0, "blur": 0.0}},
                                 edit=False)
        self.assertTrue(render.render_image(page).width() > 0)
        self.assertIsNotNone(text._shadow_pixmap(text.data["shadow"])[0])


class StyleAndPresentTest(DesignTestCase):
    def test_copy_paste_style_between_types(self):
        page = self.page()
        a = self.ctl.add_shape("rect", {"fill": "#123456", "opacity": 0.5,
                                        "shadow": {"enabled": True, "color": "#59000000", "dx": 1.0, "dy": 2.0,
                                                   "blur": 3.0}})
        b = self.ctl.add_shape("ellipse", {"fill": "#ffffff"})
        t = self.ctl.add_text("body", {"text": "x"}, edit=False)
        self.ctl._select([a])
        self.key(Qt.Key_C, Qt.ControlModifier | Qt.AltModifier)
        self.ctl._select([b, t])
        self.key(Qt.Key_V, Qt.ControlModifier | Qt.AltModifier)
        self.assertEqual(b.data["fill"], "#123456")
        self.assertEqual(b.data["shape"], "ellipse")            # la forme n'est pas du style
        self.assertEqual(t.data["opacity"], 0.5)
        self.assertNotIn("fill", t.data)                          # propriété qu'un texte n'a pas : ignorée
        self.assertTrue(t.data["shadow"]["enabled"])
        self.assertIn("#123456", self.ctl.document_colors())
        self.assertEqual(len(doc.elements(self.scene, page)), 3)  # rien de collé comme élément

    def test_presentation_navigates_pages(self):
        first = self.page(400, 300)
        second = doc.add_page(self.scene, 400, 300, after=first)
        window = self.ctl.present(start_page=second)
        try:
            self.assertEqual(window.index, 1)
            window.resize(800, 600)
            QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier))
            self.assertEqual(window.index, 0)
            QApplication.sendEvent(window, QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier))
            self.assertEqual(window.index, 0)                       # bornée
            self.assertIsNotNone(window._image(1))
        finally:
            window.close()
            settle()


class EffectsTest(DesignTestCase):
    def test_image_mask_text_outline_and_new_shapes(self):
        page = self.page(200, 200)
        source = self.tmp / "red.png"
        image = QImage(100, 100, QImage.Format_RGB32)
        image.fill(QColor("#ff0000"))
        image.save(str(source))
        self.ctl.add_image_files([source])
        item = self.ctl.selection()[0]
        doc.change(self.scene, [item], lambda i: i.data.update(x=0.0, y=0.0, w=200.0, h=200.0, mask="ellipse"),
                   "Masque")
        out = render.render_image(page)
        self.assertEqual(out.pixelColor(100, 100).name(), "#ff0000")
        self.assertEqual(out.pixelColor(3, 3).name(), "#ffffff")        # coin hors du cercle : fond de page
        text = self.ctl.add_text("body", {"text": "Contour"}, edit=False)
        doc.change(self.scene, [text], lambda i: i.data.update(text_stroke="#00ff00", text_stroke_width=3.0),
                   "Contour")
        fmt = text.text_item.document().begin().begin().fragment().charFormat()
        self.assertEqual(fmt.textOutline().widthF(), 3.0)
        heart = self.ctl.add_shape("heart")
        self.assertFalse(heart.outline().isEmpty())
        self.assertFalse(heart.shape().contains(heart.content_rect().topLeft() + QPointF(1, 1)))
        ring = self.ctl.add_shape("ring")
        self.assertFalse(ring.shape().contains(ring.content_rect().center()))   # le trou ne se clique pas


class GridTest(DesignTestCase):
    def test_grid_frames_filled_by_drop_with_cover_crop(self):
        page = self.page(1000, 500)
        cells = self.ctl.add_grid("2 colonnes")
        self.assertEqual(len(cells), 2)
        self.assertTrue(all(c.is_empty() for c in cells))
        self.assertEqual(len({c.data["group"] for c in cells}), 1)
        x, y, w, h = doc.local_box(cells[1])
        self.assertAlmostEqual(x + w, 1000 - 10, delta=0.01)        # marge = 2 % du petit côté (500)
        source = self.tmp / "large.png"
        image = QImage(400, 100, QImage.Format_RGB32)
        image.fill(QColor("#0000ff"))
        image.save(str(source))
        self.assertTrue(self.ctl.drop_files([source], self.center(cells[0])))
        filled = cells[0]
        self.assertFalse(filled.is_empty())
        self.assertEqual(filled.size(), (w, h))                     # le cadre garde sa taille
        x0, y0, x1, y1 = filled.data["crop"]
        self.assertAlmostEqual((x1 - x0) * 400 / ((y1 - y0) * 100), w / h, places=3)   # couvrant, sans déformer
        self.assertEqual(len(doc.elements(self.scene, page)), 2)    # rien d'ajouté
        self.scene.undo.undo()
        self.assertTrue(filled.is_empty())

    def test_cover_crop_and_library_fills_selected_frame(self):
        self.assertEqual(geometry.cover_crop(100, 100, 200, 100), [0.25, 0.0, 0.75, 1.0])
        self.page()
        frame = self.ctl.add_frame("ellipse")
        source = self.tmp / "sq.png"
        QImage(50, 50, QImage.Format_RGB32).save(str(source))
        self.assertTrue(self.ctl.add_image_files([source]))         # comme un clic dans la bibliothèque
        self.assertFalse(frame.is_empty())
        self.assertEqual(frame.data["mask"], "ellipse")


class GuidesTest(DesignTestCase):
    def test_guides_snap_move_with_ctrl_and_survive_save(self):
        from fm_design.menus import add_guide
        page = self.page()
        add_guide(self.ctl, page, "v", 300.0)
        item = self.ctl.add_shape("rect", {"x": 100.0, "y": 600.0, "w": 100.0, "h": 50.0})
        start = self.center(item)
        self.drag(start, start + QPointF(95, 0), mods=Qt.ControlModifier)        # bord droit 295 -> repère 300
        self.assertAlmostEqual(item.pos().x(), 200.0, delta=0.01)
        # Ctrl + glisser le repère : il bouge ; sans Ctrl : cadre de sélection, le repère reste
        line = page.mapToScene(QPointF(300, 100))
        self.drag(line, line + QPointF(100, 0))
        self.assertEqual(page.data["guides"][0]["pos"], 300.0)
        self.drag(line, line + QPointF(100, 0), mods=Qt.ControlModifier)
        self.assertAlmostEqual(page.data["guides"][0]["pos"], 400.0, delta=0.5)
        self.scene.undo.undo()
        self.assertEqual(page.data["guides"][0]["pos"], 300.0)
        self.assertTrue(self.pane.save())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        saved = [i for i in data["items"] if i["type"] == "design_page"][0]
        self.assertEqual(saved["guides"], [{"axis": "v", "pos": 300.0}])


class MoreTest(DesignTestCase):
    def test_equal_gap_and_page_ranges(self):
        found = geometry.equal_gap((48, 0, 10, 10), [(0, 0, 10, 10), (100, 0, 10, 10)], "x", 5)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found[0], 2.0)                    # 10 .. 50 .. 60 .. 100 : écarts de 40
        self.assertIsNone(geometry.equal_gap((30, 0, 10, 10), [(0, 0, 10, 10), (100, 0, 10, 10)], "x", 5))
        self.assertIsNone(geometry.equal_gap((48, 50, 10, 10), [(0, 0, 10, 10), (100, 0, 10, 10)], "x", 5))
        dx, _dy, guides = geometry.snap_move((247, 300, 100, 50), [(0, 300, 100, 50), (500, 300, 100, 50)],
                                             (2000, 2000), 5)
        self.assertAlmostEqual(dx, 3.0)
        self.assertEqual(sum(1 for g in guides if g[0] == "seg"), 2)
        self.assertEqual(geometry.parse_pages("1-3, 5, 9", 6), [0, 1, 2, 4])
        self.assertEqual(geometry.parse_pages("a", 6), [])

    def test_document_text_styles_reused(self):
        from fm_design.panels import apply_text_style, document_text_styles
        self.page()
        a = self.ctl.add_text("heading", {"text": "Titre", "font_family": "Georgia", "color": "#ff0000"}, edit=False)
        b = self.ctl.add_text("body", {"text": "Corps"}, edit=False)
        styles = document_text_styles(self.ctl)
        self.assertEqual(len(styles), 2)
        self.assertEqual(styles[0]["font_family"], "Georgia")      # le plus grand d'abord
        self.ctl._select([b])
        apply_text_style(self.ctl, styles[0])
        self.assertEqual(b.data["font_family"], "Georgia")
        self.assertEqual(b.data["text"], "Corps")                   # le texte reste
        del a


class MenusTest(DesignTestCase):
    """Chaque menu s'ouvre et chaque action (sauf celles qui ouvrent une fenêtre, « … ») s'exécute sans erreur."""

    def run_menu(self, opener):
        from PySide6.QtWidgets import QMenu
        errors = []
        old_hook = sys.excepthook
        sys.excepthook = lambda *exc: errors.append(exc)
        try:
            opener()
            settle(0.02)
            menu = QApplication.activePopupWidget()
            self.assertIsInstance(menu, QMenu)
            actions = []

            def collect(m):
                for action in m.actions():
                    if action.menu() is not None:
                        collect(action.menu())
                    elif action.text() and not action.text().endswith("…") and action.isEnabled():
                        actions.append(action)
            collect(menu)
            menu.close()
            for action in actions:
                action.trigger()
                settle(0.01)
        finally:
            sys.excepthook = old_hook
        self.assertEqual(errors, [])
        return len(actions)

    def test_all_menus(self):
        from fm_design import menus
        page = self.page()
        doc.apply_template(self.scene, templates.by_key("slide"), page=page)
        source = self.tmp / "m.png"
        QImage(30, 20, QImage.Format_RGB32).save(str(source))
        self.ctl.add_image_files([source])
        image = self.ctl.selection()[0]
        shapes = [i for i in doc.elements(self.scene, page) if isinstance(i, DesignShapeItem)]
        texts = [i for i in doc.elements(self.scene, page) if isinstance(i, DesignTextItem)]
        line = self.ctl.add_shape("line")
        anchor = self.ctl.ui.context
        everything = doc.elements(self.scene, page)
        count = 0
        for opener in (
                lambda: menus.color_menu(self.ctl, anchor, texts, "color", "Couleur"),
                lambda: menus.fill_menu(self.ctl, anchor, shapes),
                lambda: menus.stroke_menu(self.ctl, anchor, shapes + [line, image]),
                lambda: menus.shadow_menu(self.ctl, anchor, everything),
                lambda: menus.position_menu(self.ctl, anchor, everything),
                lambda: menus.shape_kind_menu(self.ctl, anchor, shapes),
                lambda: menus.mask_menu(self.ctl, anchor, [image]),
                lambda: menus.text_effects_menu(self.ctl, anchor, texts),
                lambda: menus.size_menu(self.ctl, anchor, texts),
                lambda: menus.align_menu(self.ctl, anchor, texts),
                lambda: menus.adjust_menu(self.ctl, anchor, [image]),
                lambda: menus.flip_menu(self.ctl, anchor, everything),
                lambda: menus.resize_menu(self.ctl, anchor, page),
                lambda: menus.export_menu(self.ctl, anchor)):
            count += self.run_menu(opener)
        self.ctl._select([image])
        count += self.run_menu(lambda: menus.open_context_menu(self.ctl, anchor.mapToGlobal(anchor.rect().center())))
        self.ctl._select([])
        count += self.run_menu(lambda: self.ctl.ui.page_menu(page.item_id, anchor.mapToGlobal(anchor.rect().center())))
        self.assertGreater(count, 60)
        self.scene.undo.undo()                                # tout reste annulable


class RulerTest(DesignTestCase):
    def test_rulers_toggle_and_drag_out_a_guide(self):
        from fm_design.rulers import tick_step
        self.assertEqual(tick_step(1.0), 100)
        self.assertEqual(tick_step(0.5), 200)
        self.assertEqual(tick_step(2.0), 50)
        page = self.page()
        self.key(Qt.Key_R, Qt.ShiftModifier, "R")
        self.assertTrue(self.ctl.rulers.left.isVisible())
        self.assertEqual(doc.elements(self.scene, page), [])          # Maj+R ne crée pas de rectangle
        ruler = self.ctl.rulers.left
        target = self.view.mapFromScene(page.mapToScene(QPointF(250, 300)))
        local = ruler.mapFrom(self.pane, self.view.viewport().mapTo(self.pane, target))
        ruler.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 50), QPointF(), Qt.LeftButton,
                                          Qt.LeftButton, Qt.NoModifier))
        ruler.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(), Qt.NoButton, Qt.LeftButton,
                                         Qt.NoModifier))
        self.assertIsNotNone(self.ctl.preview_guide)
        ruler.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(local), QPointF(), Qt.LeftButton,
                                            Qt.NoButton, Qt.NoModifier))
        self.assertEqual(page.data["guides"][0]["axis"], "v")
        self.assertAlmostEqual(page.data["guides"][0]["pos"], 250, delta=2.5)
        ruler.grab()                                                   # la règle se peint sans erreur
        self.key(Qt.Key_R, Qt.ShiftModifier, "R")
        self.assertFalse(self.ctl.rulers.left.isVisible())


class PrintTest(DesignTestCase):
    def test_pdf_bleed_enlarges_page(self):
        import re
        page = self.page(dm.FORMAT_SIZES["a4"][0], dm.FORMAT_SIZES["a4"][1])
        self.ctl.add_shape("rect", {"x": -50.0, "y": 0.0, "w": 200.0, "h": 200.0})      # déborde à gauche
        plain = render.export_pages([page], self.tmp / "a.pdf", "pdf")[0].read_bytes()
        bled = render.export_pages([page], self.tmp / "b.pdf", "pdf", bleed_mm=3.0, crop_marks=True)[0].read_bytes()

        def box(data):
            numbers = re.search(rb"/MediaBox \[([^\]]+)\]", data).group(1).split()
            return float(numbers[2]) - float(numbers[0]), float(numbers[3]) - float(numbers[1])
        w0, h0 = box(plain)
        w1, h1 = box(bled)
        self.assertAlmostEqual(w0, 595.3, delta=1.0)                   # A4 en points
        extra = (3.0 + render.MARKS_MM) * 2 * 72 / 25.4
        self.assertAlmostEqual(w1 - w0, extra, delta=1.0)
        self.assertAlmostEqual(h1 - h0, extra, delta=1.0)


class RichTextTest(DesignTestCase):
    def test_bold_part_of_text_saved_undone_and_scaled(self):
        from PySide6.QtGui import QTextCursor
        self.page()
        text = self.ctl.add_text("body", {"text": "Bonjour le monde", "bold": False}, edit=False)
        index = self.scene.undo.index()
        self.ctl.edit_text(text)
        editor = text.text_item
        cursor = editor.textCursor()
        cursor.setPosition(8)
        cursor.setPosition(10, QTextCursor.KeepAnchor)             # « le »
        editor.setTextCursor(cursor)
        QApplication.sendEvent(self.view, QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.ControlModifier))
        QApplication.sendEvent(self.view, QKeyEvent(QEvent.KeyPress, Qt.Key_Greater,
                                                    Qt.ControlModifier | Qt.ShiftModifier))
        self.assertEqual(text.data["bold"], False)                 # la boîte n'est pas en gras
        self.view.finish_text_edit()
        settle()
        spans = text.to_dict()["spans"]
        self.assertEqual(len(spans), 1)
        self.assertEqual((spans[0]["start"], spans[0]["end"], spans[0]["bold"]), (8, 10, True))
        self.assertGreater(spans[0]["size"], text.data["font_size"])
        self.assertEqual(self.scene.undo.index(), index + 1)
        # sauvegarde / réouverture
        self.assertTrue(self.pane.save())
        other = board_ui.BoardPane(self.host)
        _PANES.append(other)
        self.assertTrue(other.open(self.path))
        again = other.scene.item(text.item_id)
        self.assertEqual(again.to_dict()["spans"], spans)
        # agrandir la boîte agrandit aussi la partie stylée
        doc.scale_element(text, 2.0)
        self.assertAlmostEqual(text.data["spans"][0]["size"], spans[0]["size"] * 2, delta=0.01)
        text.apply(text.data)
        # annuler l'édition : plus aucune partie stylée
        self.scene.undo.setIndex(index)
        self.assertEqual(text.to_dict()["spans"], [])

    def test_spans_normalized(self):
        item = model.normalize_item({"id": "t", "type": "design_text", "text": "abc",
                                     "spans": [{"start": 2, "end": 1, "bold": True}, {"start": 0, "end": 2},
                                               {"start": 0, "end": 2, "italic": True, "size": "x"}]})
        self.assertEqual(item["spans"], [{"start": 0, "end": 2, "italic": True}])


if __name__ == "__main__":
    unittest.main()
