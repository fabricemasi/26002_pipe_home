"""Textes du module CAD (TEXTE, MTEXTE, modification en place) et DECOMPOSER (board/cad_text.py,
cad_items.CadTextItem, cad_commands.TextCommand / MTextCommand / TextEditCommand / ExplodeCommand)."""
import _isolate  # noqa: F401  (jamais les vrais reglages / presets de l'utilisateur)

import math
import unittest

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import test_cad as base
from test_cad import APP, CadBoardCase
from board import cad_export, cad_import, cad_model, cad_shapes, cad_text, model


def layout(**data):
    return cad_text.layout({"pos": [0.0, 0.0], "height": 10.0, "text": "ABC", **data})


class TextGeometryTest(unittest.TestCase):
    def test_justification_places_the_text_around_the_insertion_point(self):
        left = layout(justify="L")
        self.assertAlmostEqual(left["lines"][0][1], 0.0)                     # ligne de base a gauche
        self.assertAlmostEqual(left["lines"][0][2], 0.0)
        right = layout(justify="R")
        self.assertAlmostEqual(right["box"][2], 0.0)                          # fin du texte au point
        top = layout(justify="TL")
        self.assertAlmostEqual(top["box"][3], 0.0)                            # haut des capitales au point
        self.assertAlmostEqual(top["lines"][0][2], -10.0)
        middle = layout(justify="MC")
        self.assertAlmostEqual(middle["box"][1] + middle["box"][3], 0.0)      # centre du cadre au point
        self.assertAlmostEqual(middle["box"][0] + middle["box"][2], 0.0)
        bottom = layout(justify="BL")
        self.assertAlmostEqual(bottom["box"][1], 0.0)

    def test_rotation_turns_the_frame_and_the_distance_is_zero_inside(self):
        found = layout(rot=90.0)
        xs = [c[0] for c in found["corners"]]
        self.assertLessEqual(max(xs), cad_text.DESCENT * 10.0 + 1e-9)       # tourne de 90 : le texte monte
        self.assertEqual(cad_text.distance(found, (-5.0, 5.0)), 0.0)
        self.assertGreater(cad_text.distance(found, (50.0, 0.0)), 0.0)

    def test_width_wraps_at_spaces_and_paragraphs_are_kept(self):
        found = layout(text="un deux trois quatre\nfin", width=30.0, mtext=True)
        texts = [line for line, _x, _y in found["lines"]]
        self.assertGreater(len(texts), 2)
        self.assertEqual(texts[-1], "fin")
        self.assertEqual(" ".join(texts[:-1]), "un deux trois quatre")       # rien de perdu
        step = found["lines"][0][2] - found["lines"][1][2]
        self.assertAlmostEqual(step, 10.0 * cad_text.LINE_SPACING)

    def test_transformations_move_turn_scale_and_keep_a_mirror_readable(self):
        data = {"pos": [10.0, 0.0], "rot": 0.0, "height": 5.0, "width": 0.0}
        out = cad_shapes.rotated("cad_text", data, (0.0, 0.0), 90.0)
        self.assertAlmostEqual(out["pos"][1], 10.0)
        self.assertAlmostEqual(out["rot"], 90.0)
        out = cad_shapes.mirrored("cad_text", data, (0.0, -1.0), (0.0, 1.0))  # axe vertical : texte lisible
        self.assertAlmostEqual(out["pos"][0], -10.0)
        self.assertAlmostEqual(out["rot"], 0.0)
        out = cad_shapes.scaled("cad_text", data, (0.0, 0.0), 2.0)
        self.assertAlmostEqual(out["height"], 10.0)
        self.assertAlmostEqual(out["pos"][0], 20.0)
        self.assertEqual(cad_shapes.translated("cad_text", data, (1.0, 2.0))["pos"], [11.0, 2.0])

    def test_normalize_keeps_unknown_fields_and_fixes_bad_values(self):
        item = {"type": "cad_text", "text": "a", "height": -3, "justify": "??", "future": 1}
        cad_model.normalize_entity(item)
        self.assertEqual(item["justify"], "L")
        self.assertGreater(item["height"], 0)
        self.assertEqual(item["future"], 1)


class TextCommandTest(CadBoardCase):
    def texts(self):
        return [i for i in self.ctl.cad_items() if i.kind == "cad_text"]

    def keys(self, text):
        for ch in text:
            QTest.keyClick(self.pane.view, ch)
        APP.processEvents()

    def key(self, key, mods=Qt.NoModifier):
        QTest.keyClick(self.pane.view, key, mods)
        APP.processEvents()

    def send(self, kind, doc_point):
        vp = self.pane.view.viewport()
        pos = QPointF(self.vp(doc_point))
        types = {"press": QEvent.MouseButtonPress, "release": QEvent.MouseButtonRelease,
                 "double": QEvent.MouseButtonDblClick}
        held = Qt.NoButton if kind == "release" else Qt.LeftButton
        QApplication.sendEvent(vp, QMouseEvent(types[kind], pos, vp.mapToGlobal(pos), Qt.LeftButton, held,
                                               Qt.NoModifier))
        APP.processEvents()

    def double_click(self, doc_point):
        self.move(doc_point)
        for kind in ("press", "release", "double", "release"):
            self.send(kind, doc_point)

    def center(self, item):
        x0, y0, x1, y1 = item.doc_bounds()
        return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)

    # -- TEXTE --
    def test_text_shows_while_typing_spaces_included_one_line_per_enter_one_undo_step(self):
        self.type("TEXTE", "10,20", "5", "0")
        self.assertEqual(self.ctl.prompt().kind, "text")
        self.keys("Bonjour le monde")
        self.assertEqual([i.text() for i in self.texts()], ["Bonjour le monde"])       # visible en tapant
        self.key(Qt.Key_Return)
        self.keys("ligne 2")
        self.key(Qt.Key_Return)
        self.key(Qt.Key_Return)                                              # ligne vide : fin
        self.assertIsNone(self.ctl.command)
        texts = sorted(self.texts(), key=lambda i: -i.points()[0][1])
        self.assertEqual([i.text() for i in texts], ["Bonjour le monde", "ligne 2"])
        self.assertEqual(texts[0].points()[0], (10.0, 20.0))
        self.assertAlmostEqual(texts[1].points()[0][1], 20.0 - 5.0 * cad_text.LINE_SPACING)
        self.assertAlmostEqual(texts[0].data["height"], 5.0)
        self.pane.scene.undo.undo()
        self.assertEqual(self.texts(), [])                                   # une seule etape
        self.pane.scene.undo.redo()
        self.assertEqual(len(self.texts()), 2)

    def test_backspace_paste_and_escape_keeps_what_was_typed(self):
        QApplication.clipboard().setText("collé\nici")
        self.type("DT", "0,0", "", "")
        self.keys("Abx")
        self.key(Qt.Key_Backspace)
        self.key(Qt.Key_V, Qt.ControlModifier)
        self.key(Qt.Key_Escape)
        self.assertIsNone(self.ctl.command)
        self.assertEqual([i.text() for i in self.texts()], ["Abcollé ici"])  # une ligne : saut remplace
        self.pane.scene.undo.undo()
        self.assertEqual(self.texts(), [])

    def test_justify_option_and_a_click_starts_the_next_line_elsewhere(self):
        self.type("TEXTE", "J", "MC", "0,0", "4", "90")
        self.keys("A")
        self.click((200, 100))
        self.keys("B")
        self.key(Qt.Key_Return)
        self.key(Qt.Key_Return)
        found = {i.text(): i for i in self.texts()}
        self.assertEqual(set(found), {"A", "B"})
        self.assertEqual(found["A"].data["justify"], "MC")
        self.assertAlmostEqual(found["A"].data["rot"], 90.0)
        self.assertEqual(found["B"].points()[0], (200.0, 100.0))

    def test_text_style_comes_from_the_settings(self):
        self.ctl.apply_settings(dict(self.ctl.settings, board_cad_text_height=700, board_cad_text_font="Consolas",
                                     board_cad_text_justify="TR"))
        self.type("TEXTE", "0,0", "", "")
        self.keys("x")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        self.assertAlmostEqual(item.data["height"], 7.0)                     # centiemes de l'unite (px ici)
        self.assertEqual(item.data["font"], "Consolas")
        self.assertEqual(item.data["justify"], "TR")

    # -- MTEXTE --
    def test_mtext_frame_enter_is_a_paragraph_ctrl_enter_finishes_one_entity(self):
        self.type("MT", "0,0", "60,-40")
        self.keys("un deux trois quatre cinq six")
        self.key(Qt.Key_Return)
        self.keys("fin")
        self.key(Qt.Key_Return, Qt.ControlModifier)
        self.assertIsNone(self.ctl.command)
        items = self.texts()
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.text(), "un deux trois quatre cinq six\nfin")
        self.assertTrue(item.data["mtext"])
        self.assertAlmostEqual(item.data["width"], 60.0)
        self.assertEqual(item.data["justify"], "TL")
        self.assertEqual(item.points()[0], (0.0, 0.0))                       # haut gauche du cadre
        self.assertGreater(len(item.layout()["lines"]), 2)                   # coupe a la largeur du cadre

    def test_mtext_empty_is_not_created(self):
        self.type("MT", "0,0", "60,-40")
        self.key(Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual(self.texts(), [])

    # -- modification, selection, transformations --
    def test_double_click_edits_the_text_in_place_in_one_undo_step(self):
        self.type("TEXTE", "0,0", "10", "0")
        self.keys("Avant")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        self.double_click(self.center(item))
        self.assertEqual(self.ctl.command.NAME, "TEXTEDIT")
        self.assertEqual(self.ctl.buffer, "Avant")
        for _ in range(5):
            self.key(Qt.Key_Backspace)
        self.keys("Apres")
        self.assertEqual(item.text(), "Apres")                               # en place, en tapant
        self.key(Qt.Key_Return)
        self.assertEqual(item.text(), "Apres")
        self.pane.scene.undo.undo()
        self.assertEqual(self.texts()[0].text(), "Avant")

    def test_escape_while_editing_restores_the_original(self):
        self.type("TEXTE", "0,0", "10", "0")
        self.keys("Garde")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        self.pane.scene.clearSelection()
        item.setSelected(True)
        self.type("ED")
        self.keys(" moi")
        self.assertEqual(item.text(), "Garde moi")
        self.key(Qt.Key_Escape)
        self.assertEqual(item.text(), "Garde")

    def test_click_selects_window_selects_and_move_rotate_scale_follow(self):
        self.type("TEXTE", "0,0", "10", "0")
        self.keys("Texte")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        self.click(self.center(item))
        self.assertEqual(self.ctl.selection(), [item])
        self.type("M", "0,0", "100,0")
        self.assertEqual(item.points()[0], (100.0, 0.0))
        item.setSelected(True)
        self.type("SC", "100,0", "2")
        self.assertAlmostEqual(item.data["height"], 20.0)
        item.setSelected(True)
        self.type("RO", "100,0", "30")
        self.assertAlmostEqual(item.data["rot"], 30.0)
        self.pane.scene.clearSelection()
        x0, y0, x1, y1 = item.doc_bounds()
        self.click((x0 - 20, y0 - 20))
        self.click((x1 + 20, y1 + 20))                                       # fenetre gauche -> droite : contenu
        self.assertEqual(self.ctl.selection(), [item])

    def test_text_is_never_a_snap_target_nor_a_hatch_boundary(self):
        self.type("TEXTE", "0,0", "10", "0")
        self.keys("Rien")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        self.assertEqual(item.snap_primitives(), [])
        self.assertEqual(self.ctl.hatch_segments(), [])

    def test_copy_keeps_text_and_style(self):
        self.type("TEXTE", "0,0", "10", "45")
        self.keys("Copie")
        self.key(Qt.Key_Escape)
        self.texts()[0].setSelected(True)
        self.type("CO", "0,0", "50,50", "")
        texts = self.texts()
        self.assertEqual(len(texts), 2)
        self.assertTrue(all(i.text() == "Copie" and abs(i.data["rot"] - 45.0) < 1e-9 for i in texts))

    def test_saved_text_comes_back_the_same(self):
        self.type("MT", "0,0", "80,-30")
        self.keys("deux")
        self.key(Qt.Key_Return)
        self.keys("lignes")
        self.key(Qt.Key_Return, Qt.ControlModifier)
        item = self.texts()[0]
        data = item.to_dict()
        again = cad_model.normalize_entity(dict(data))
        for key in ("text", "pos", "height", "rot", "width", "justify", "mtext", "font"):
            self.assertEqual(again[key], data[key], key)

    def test_properties_change_content_height_and_justification(self):
        self.type("TEXTE", "0,0", "10", "0")
        self.keys("Propriétés")
        self.key(Qt.Key_Escape)
        item = self.texts()[0]
        item.setSelected(True)
        from board.cad_ui import PropertyRows
        handler = PropertyRows(self.ctl.ui)
        keys = [spec[0] for spec in handler.specs()]
        for key in ("text_value", "text_height", "text_rot", "text_justify", "text_font", "text_spacing"):
            self.assertIn(key, keys)
        self.assertNotIn("length", keys)
        handler._set_text_value("Nouveau\\Pparagraphe")
        handler._set_text_height("12.5")
        handler._set_text_justify("MC — Milieu centre")
        self.assertEqual(item.text(), "Nouveau\nparagraphe")
        self.assertAlmostEqual(item.data["height"], 12.5)
        self.assertEqual(item.data["justify"], "MC")

    def test_dxf_export_then_import_gives_the_same_texts(self):
        self.type("TEXTE", "J", "BR", "10,20", "5", "30")
        self.keys("Simple")
        self.key(Qt.Key_Escape)
        self.type("MT", "0,0", "100,-40")
        self.keys("Multi")
        self.key(Qt.Key_Return)
        self.keys("ligne")
        self.key(Qt.Key_Return, Qt.ControlModifier)
        path = self.dir / "textes.dxf"
        cad_export.export_dxf(self.pane.scene, path, "raw")
        data, report = cad_import.read_drawing(path)
        texts = sorted((i for i in data["items"] if i["type"] == "cad_text"), key=lambda i: i["text"])
        self.assertEqual([t["text"] for t in texts], ["Multi\nligne", "Simple"])
        multi, simple = texts
        self.assertTrue(multi["mtext"])
        self.assertAlmostEqual(multi["width"], 100.0, places=3)
        self.assertEqual(multi["justify"], "TL")
        self.assertFalse(simple["mtext"])
        self.assertEqual(simple["justify"], "BR")
        self.assertAlmostEqual(simple["rot"], 30.0, places=6)
        self.assertAlmostEqual(simple["height"], 5.0, places=6)
        self.assertAlmostEqual(simple["pos"][0], 10.0, places=6)
        self.assertNotIn("TEXT", report["ignored"])


class ExplodeTest(CadBoardCase):
    def test_polyline_becomes_lines_and_arcs_with_its_properties_in_one_step(self):
        self.type("PL", "0,0", "100,0", "A", "100,100", "L", "0,100", "")
        pline = [i for i in self.ctl.cad_items() if i.kind == "cad_pline"][0]
        self.ctl.change_entities([pline], {"color": "#ff0000"}, "rouge")
        pline.setSelected(True)
        self.type("DECOMPOS")
        kinds = sorted(i.kind for i in self.ctl.cad_items())
        self.assertEqual(kinds, ["cad_arc", "cad_line", "cad_line"])
        self.assertTrue(all(i.data["color"] == "#ff0000" for i in self.ctl.cad_items()))
        arc = [i for i in self.ctl.cad_items() if i.kind == "cad_arc"][0]
        self.assertAlmostEqual(arc.data["radius"], 50.0)
        ends = sorted(p for i in self.ctl.cad_items() for p in i.points())
        self.assertEqual(ends[0], (0.0, 0.0))
        self.pane.scene.undo.undo()
        self.assertEqual([i.kind for i in self.ctl.cad_items()], ["cad_pline"])

    def test_rectangle_and_dimension_explode_lines_and_other_objects_stay(self):
        self.type("REC", "0,0", "50,30")
        self.type("DLI", "0,0", "50,0", "25,-20")
        self.type("C", "200,0", "10")
        self.type("X", "TOUT", "")
        kinds = sorted(i.kind for i in self.ctl.cad_items())
        self.assertEqual(kinds.count("cad_circle"), 1)                       # ne se decompose pas
        self.assertNotIn("cad_pline", kinds)
        self.assertNotIn("cad_dim", kinds)
        self.assertEqual(kinds.count("cad_text"), 1)                         # texte de la cotation
        text = [i for i in self.ctl.cad_items() if i.kind == "cad_text"][0]
        self.assertEqual(text.text(), "50")
        self.assertGreaterEqual(kinds.count("cad_line"), 4 + 3)              # rectangle + traits de la cote


if __name__ == "__main__":
    unittest.main()
