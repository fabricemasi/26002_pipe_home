"""Module Illustrator : barres FLOTTANTES du système de fm_theme (`fm_illustrator/bars.py`, `ui.IllustratorChrome`, gestionnaire
`fm_theme/bar_manager.py` ; maquette Claude Design « Barres d'outils flottantes »). Toutes les palettes du module (outils,
fond / contour, propriétés, objet, texte) sont des barres enregistrées dans `board_bars["illustrator"]` ; la barre des modules
n'est pas touchée."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import time
import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from test_illustrator import IllTestCase, settle
from fm_board import ui as board_ui
from fm_board.bars import BoardBars, BoardTool
from fm_illustrator import bars as ill_bars, ui as ill_ui
from fm_theme.palette import PaletteSliderBar


class DefaultStateTest(unittest.TestCase):
    """La disposition par défaut, sans Qt : chaque outil dans une barre, aucune case en double."""

    def test_every_tool_of_the_toolbox_is_in_exactly_one_tool_bar(self):
        tools = [name for group in ill_ui.TOOL_GROUPS for name, _glyph in group]
        listed = [key for _title, keys in ill_bars.TOOL_BARS for key in keys]
        self.assertEqual(sorted(k for k in listed if k not in ("fill_stroke", "swap")), sorted(tools))
        self.assertEqual(len(listed), len(set(listed)))

    def test_cells_are_free_and_inside_their_grid(self):
        seen = set()
        for bar in ill_bars.default_state()["bars"]:
            cells = set()
            for key, (col, row, width) in bar["items"].items():
                self.assertNotIn(key, seen)                       # une clé n'est que dans une barre
                seen.add(key)
                for c in range(col, col + width):
                    self.assertNotIn((c, row), cells, (bar["id"], key))
                    cells.add((c, row))
                self.assertLessEqual(col + width, bar["cols"], (bar["id"], key))
                self.assertLess(row, bar["rows"], (bar["id"], key))

    def test_the_tool_bars_are_docked_left_one_behind_the_other_and_the_rest_is_on_top_or_floats(self):
        bars = {b["id"]: b for b in ill_bars.default_state()["bars"]}
        self.assertEqual([bars[f"b{i}"]["dock"] for i in range(1, 5)], ["left"] * 4)
        self.assertEqual([bars[f"b{i}"]["after"] for i in range(1, 5)], ["", "b1", "b2", "b3"])
        self.assertEqual((bars["b5"]["dock"], bars["b6"]["dock"], bars["b6"]["after"]), ("top", "top", "b5"))
        self.assertIsNone(bars["b7"]["dock"])                      # « Texte » : flottante


class FloatingBarsTest(IllTestCase):
    def mgr(self):
        return self.ctl.ui.bars.manager

    def drag_out(self, key, x=900, y=500):
        """Glisser (méthodes du gestionnaire, comme Ctrl + glisser) : l'élément `key` lâché dans le vide du board."""
        mgr = self.mgr()
        bar = mgr.bar_of(key)
        item = bar._items[key]
        mgr.begin_item_drag(bar, item, bar.mapToGlobal(item.widget.geometry().center()))
        mgr.item_drag_to(self.pane.mapToGlobal(QPoint(x, y)))
        mgr.end_item_drag()

    def test_every_palette_is_a_registered_bar_saved_under_the_module_name(self):
        ui = self.ctl.ui
        self.assertIsInstance(ui.bars, BoardBars)
        self.assertEqual(ui.bars.module, "illustrator")
        self.assertEqual([b.title() for b in self.mgr().bars],
                         ["Sélection", "Tracé", "Créer", "Transformer", "Propriétés", "Objet", "Texte"])
        placed = {key for bar in self.mgr().bars for key in bar.keys()}
        self.assertEqual(placed, set(self.mgr().widgets))              # aucun élément perdu, aucun hors barre
        for name in ("select", "pen", "rect", "zoom", "fill_stroke", "swap", "fill", "stroke", "stroke_width", "opacity",
                     "object", "brush", "align", "pathfinder", "effects", "artboards", "layers", "export", "title",
                     "font", "size", "paragraph"):
            self.assertIn(name, placed)
        self.assertIsInstance(ui.opacity, PaletteSliderBar)
        self.assertTrue(all(isinstance(b, BoardTool) for b in ui._tool_buttons.values()))
        self.drag_out("pen")
        self.assertIn("illustrator", self.pane._settings["board_bars"])    # chaque module a sa disposition
        self.assertNotIn("miro", self.pane._settings["board_bars"])

    def test_the_bars_are_clipped_to_the_right_of_the_module_bar(self):
        pane = self.pane
        self.assertTrue(pane._modulebar.isVisible())
        self.assertEqual(pane._modulebar.geometry().left(), 0)
        for bar in self.mgr().bars:
            if bar.dock == "left":
                self.assertEqual(bar.x(), pane.left_edge())              # collées au bord de la zone, pas sous la barre des modules
        self.assertEqual(self.mgr().area().left(), pane.left_edge())
        first, second = self.mgr().bar("b1"), self.mgr().bar("b2")
        self.assertEqual(second.y(), first.y() + first.height())        # l'une derrière l'autre
        top = self.mgr().bar("b5")
        self.assertEqual(top.y(), 0)
        self.assertGreaterEqual(top.x(), self.mgr().bar("b1").geometry().right())   # en haut, à droite des outils

    def test_the_bars_follow_the_module_and_the_miro_bars_are_hidden_meanwhile(self):
        mgr = self.mgr()
        self.assertTrue(mgr.bar("b1").isVisible())
        self.assertFalse(self.pane._miro_bars.manager.bar("b1").isVisible())
        self.pane.set_module("design")
        self.assertFalse(mgr.bar("b1").isVisible())
        self.assertFalse(mgr.bar("b5").isVisible())
        self.pane.set_module("illustrator")
        self.assertTrue(mgr.bar("b1").isVisible())
        self.assertTrue(mgr.bar("b5").isVisible())
        self.pane.set_module(None)
        self.assertFalse(mgr.bar("b1").isVisible())

    def test_a_click_on_a_tool_chooses_it_and_lights_its_cell(self):
        ui = self.ctl.ui
        ui._tool_buttons["pen"].click()
        settle()
        self.assertEqual(self.ctl.tool, "pen")
        self.assertTrue(ui._tool_buttons["pen"].active)
        self.assertFalse(ui._tool_buttons["select"].active)
        ui._tool_buttons["rect"].click()
        settle()
        self.assertTrue(ui._tool_buttons["rect"].active)
        self.assertFalse(ui._tool_buttons["pen"].active)

    def test_a_tool_dropped_in_the_void_becomes_a_bar_that_is_saved_and_restored(self):
        self.drag_out("star")
        mgr = self.mgr()
        new = mgr.bar_of("star")
        self.assertNotEqual(new.bar_id, "b3")
        self.assertEqual(new.keys(), ["star"])
        self.assertNotIn("star", mgr.bar("b3").keys())
        saved = self.pane._settings["board_bars"]["illustrator"]
        self.assertIn("star", next(b for b in saved["bars"] if b["id"] == new.bar_id)["items"])
        other = board_ui.BoardPane(self.host, {"board_bars": self.pane._settings["board_bars"]})   # autre ouverture
        other.open(self.path)
        other.resize(1400, 900)
        other.show()
        other.set_module("illustrator")
        settle(0.05)
        again = other.illustrator.ui.bars.manager
        self.assertEqual(again.bar_of("star").bar_id, new.bar_id)
        self.assertEqual(again.bar_of("star").keys(), ["star"])
        self.assertTrue(again.bar_of("star").isVisible())
        other._autosave.stop()

    def test_the_tools_still_work_after_the_user_moved_them(self):
        self.drag_out("ellipse")
        button = self.ctl.ui._tool_buttons["ellipse"]
        button.click()
        settle()
        self.assertEqual(self.ctl.tool, "ellipse")
        self.assertTrue(button.active)

    def test_reset_returns_to_the_default_layout(self):
        self.drag_out("pen")
        self.ctl.ui.bars.reset()
        self.assertEqual(self.mgr().bar_of("pen").bar_id, "b2")
        self.assertEqual(len(self.mgr().bars), 7)

    def test_a_saved_layout_from_an_older_version_places_the_new_tools_somewhere(self):
        """Une disposition enregistrée sans un outil (ajouté depuis) : il va dans une barre, rien ne se perd."""
        saved = ill_bars.default_state()
        for bar in saved["bars"]:
            bar["items"].pop("star", None)
        self.pane._settings["board_bars"] = {"illustrator": saved}
        self.ctl.ui.bars.restore()
        self.assertIsNotNone(self.mgr().bar_of("star"))
        self.assertEqual(set(self.mgr().widgets), {k for b in self.mgr().bars for k in b.keys()})

    def test_the_bars_follow_the_fm_theme_palette_settings_at_once(self):
        """Aspect = réglages `palette_*` (éditeur fm_theme) : jamais de style inventé ; changés, les barres suivent."""
        from fm_theme import palette as fm_palette
        self.addCleanup(self.pane.apply_settings, {})
        bar = self.mgr().bar("b1")
        before = bar.width()
        self.pane.apply_settings({"palette_cell_size": 48, "palette_bg_color": "#ff0000"})
        self.assertEqual(fm_palette.LOOK["bg"], "#ff0000")
        self.assertGreater(bar.width(), before)                         # cases plus grandes : la barre grandit
        self.assertEqual(bar.size(), bar.grid_size())
        self.assertEqual(self.ctl.ui._tool_buttons["pen"].width(), 48)
        self.assertEqual(self.ctl.ui.fill_stroke.width(), 48)           # le témoin fond / contour est une case comme les autres
        self.pane.apply_settings({})
        self.assertEqual(bar.width(), before)

    def test_the_old_bar_attributes_still_answer(self):
        ui = self.ctl.ui
        self.assertIs(ui.tools, self.mgr().bar_of("select"))
        self.assertIs(ui.control, self.mgr().bar_of("opacity"))
        self.assertTrue(ui.tools.isVisible())
        self.drag_out("select")
        self.assertIs(ui.tools, self.mgr().bar_of("select"))           # suit l'élément, pas une barre figée
        self.mgr().remove_bar(self.mgr().bar_of("opacity"))            # barre supprimée : un widget caché, pas une erreur
        self.assertFalse(ui.control.isVisible())


class PropertiesTest(IllTestCase):
    def test_the_title_and_the_buttons_follow_the_selection(self):
        ui = self.ctl.ui
        self.ctl.select([])
        ui.sync()
        self.assertEqual(ui.title.text_value(), "Aucune sélection")
        a = self.rect(100, 100, 80, 50)
        self.ctl.select([a])
        ui.sync()
        self.assertEqual(ui.title.text_value(), "Tracé")
        b = self.rect(260, 100, 80, 50)
        self.ctl.select([a, b])
        ui.sync()
        self.assertEqual(ui.title.text_value(), "2 objets")
        self.assertEqual(ui.fill_button._swatch, a.data.get("fill") or "#ffffff")
        self.assertTrue(ui.width_button.text_value().endswith("pt"))

    def test_the_title_is_not_a_button(self):
        title = self.ctl.ui.title
        self.assertFalse(title.underMouse())
        self.assertEqual(title.cursor().shape(), Qt.ArrowCursor)

    def test_the_opacity_slider_changes_the_selection_and_shows_its_value_without_firing(self):
        ui = self.ctl.ui
        a = self.rect(100, 100, 80, 50)
        self.ctl.select([a])
        ui.opacity.setValue(40)
        self.ctl.scene.commit_live()
        self.assertAlmostEqual(a.data["opacity"], 0.4)
        other = self.rect(260, 100, 80, 50)                              # un autre objet : le curseur le montre
        other.data["opacity"] = 0.7
        self.ctl.select([other])
        ui.sync()
        self.assertEqual(ui.opacity.value(), 70)
        self.assertAlmostEqual(other.data["opacity"], 0.7)               # rien n'a été émis par la mise à jour
        self.assertEqual(ui.opacity._value_text, "70 %")

    def test_the_fill_and_stroke_menus_open_from_the_bar_buttons(self):
        ui = self.ctl.ui
        opened = []
        with mock.patch.object(ill_ui, "_popup", lambda menu, anchor: opened.append(anchor)):
            ui.fill_button.click()
            ui.stroke_button.click()
            ui.width_button.click()
            ui.object_button.click()
            ui.board_button.click()
            ui.export_button.click()
            ui.effects_button.click()
        self.assertGreaterEqual(len(opened), 5)
        self.assertIn(ui.fill_button, opened)

    def test_the_layers_panel_stays_clear_of_the_bars(self):
        ui = self.ctl.ui
        ui.layers_button.click()
        settle()
        self.assertTrue(ui.layers.isVisible())
        self.assertTrue(ui.layers_button.active)
        for bar in ui.bars.manager.bars:
            if bar.isVisible():
                self.assertFalse(bar.geometry().intersects(ui.layers.geometry()), bar.title())
        self.assertLessEqual(ui.layers.geometry().right(), self.pane.width())
        ui.layers_button.click()
        settle()
        self.assertFalse(ui.layers.isVisible())
        self.assertFalse(ui.layers_button.active)


class TextBarTest(IllTestCase):
    def bar(self):
        return self.ctl.ui.bars.manager.bar_of("font")

    def test_the_text_bar_is_visible_only_while_a_text_is_chosen(self):
        ui = self.ctl.ui
        self.ctl.select([])
        ui.sync()
        self.assertFalse(self.bar().isVisible())
        text = self.ctl.new_text(QPointF(100, 100), text="Bonjour")
        self.ctl.select([text])
        settle(0.05)
        self.assertTrue(self.bar().isVisible())
        self.assertEqual(ui.title.text_value(), "Texte")
        self.assertEqual(ui.size_button.text_value(), look_display(text.data["font_size"]))
        self.assertTrue(ui.font_button.text_value())
        self.ctl.select([])
        settle(0.05)
        self.assertFalse(self.bar().isVisible())
        self.assertTrue(ui.bars.manager.bar("b5").isVisible())                   # « Propriétés » reste là

    def test_the_text_buttons_open_their_menus(self):
        ui = self.ctl.ui
        text = self.ctl.new_text(QPointF(100, 100), text="Bonjour")
        self.ctl.select([text])
        settle(0.05)
        opened = []
        with mock.patch.object(ill_ui, "_popup", lambda menu, anchor: opened.append(anchor)):
            ui.size_button.click()
            ui.paragraph_button.click()
        self.assertEqual(opened, [ui.size_button, ui.paragraph_button])

    def test_a_text_button_moved_into_another_bar_keeps_working_and_its_cell(self):
        ui = self.ctl.ui
        mgr = ui.bars.manager
        item = mgr.bar_of("size")._items["size"]
        mgr.begin_item_drag(mgr.bar_of("size"), item, mgr.bar_of("size").mapToGlobal(item.widget.geometry().center()))
        mgr.item_drag_to(self.pane.mapToGlobal(QPoint(900, 500)))
        mgr.end_item_drag()
        self.assertNotEqual(mgr.bar_of("size").bar_id, "b7")
        text = self.ctl.new_text(QPointF(100, 100), text="x")
        self.ctl.select([text])
        settle(0.05)
        self.assertTrue(mgr.bar_of("size").isVisible())                  # sa nouvelle barre apparaît avec lui
        self.assertTrue(mgr.bar_of("font").isVisible())
        self.ctl.select([])
        settle(0.05)
        self.assertFalse(mgr.bar_of("size").isVisible())


def look_display(value):
    from fm_illustrator import look
    return look.to_display(float(value))


class FillStrokeToolTest(IllTestCase):
    def tool(self):
        return self.ctl.ui.fill_stroke

    def click(self, widget, pos, ctrl=False):
        mods = Qt.ControlModifier if ctrl else Qt.NoModifier
        with mock.patch.object(QApplication, "keyboardModifiers", return_value=mods):
            QTest.mouseClick(widget, Qt.LeftButton, mods, pos)

    def test_the_witness_is_a_cell_of_a_bar_and_follows_the_bar_cell_size(self):
        tool = self.tool()
        self.assertIs(tool.parentWidget(), self.ctl.ui.bars.manager.bar_of("fill_stroke"))
        self.assertTrue(tool.isVisible())
        fill_rect, stroke_rect = tool._rects()
        self.assertTrue(tool.rect().contains(fill_rect.toRect()))
        self.assertTrue(tool.rect().adjusted(-1, -1, 1, 1).contains(stroke_rect.toRect()))
        self.assertGreater(tool.grab().width(), 10)

    def test_a_click_on_the_back_square_brings_it_forward_then_the_front_one_opens_the_color(self):
        ui = self.ctl.ui
        tool = self.tool()
        picked = []
        tool.pick = lambda which, anchor: picked.append((which, anchor))
        self.assertEqual(self.ctl.focus, "fill")
        fill_rect, stroke_rect = tool._rects()
        self.click(tool, stroke_rect.center().toPoint() + QPoint(8, 8))      # le contour est derrière
        settle()
        self.assertEqual(self.ctl.focus, "stroke")
        self.assertEqual(picked, [])
        self.click(tool, stroke_rect.center().toPoint() + QPoint(8, 8))      # maintenant devant : sa couleur
        self.assertEqual(picked, [("stroke", tool)])
        self.assertIs(ui.fill_stroke, tool)

    def test_a_drag_does_not_pick_a_color_it_moves_the_witness(self):
        # Barres de fm_theme (spec docs/agents/barres_outils_spec.md § 6) : au-delà de 4 px, l'appui devient un
        # déplacement ; seul un clic choisit une couleur.
        tool = self.tool()
        picked = []
        tool.pick = lambda which, anchor: picked.append(which)
        mgr = self.ctl.ui.bars.manager
        fill_rect, _stroke = tool._rects()
        start = fill_rect.center().toPoint()
        QTest.mousePress(tool, Qt.LeftButton, Qt.NoModifier, start)
        far = tool.mapFromGlobal(self.pane.mapToGlobal(QPoint(self.pane.width() // 2, self.pane.height() // 2)))
        QTest.mouseMove(tool, start + QPoint(10, 0))
        QTest.mouseMove(tool, far)
        self.assertTrue(mgr.item_dragging(tool))
        QTest.mouseRelease(tool, Qt.LeftButton, Qt.NoModifier, far)
        self.assertEqual(picked, [])
        self.assertEqual(self.ctl.focus, "fill")

    def test_the_picture_follows_the_colors_and_the_focus(self):
        tool = self.tool()
        before = tool.extra_key()
        a = self.rect(100, 100, 80, 50)
        a.data["fill"] = "#ff0000"
        self.ctl.select([a])
        self.assertNotEqual(tool.extra_key(), before)
        key = tool.extra_key()
        self.ctl.focus = "stroke"
        self.assertNotEqual(tool.extra_key(), key)
        self.assertIn("#ff0000", tool.extra_key())


class FluidityTest(IllTestCase):
    """Fluidité (AGENTS.md) : le clic d'un outil, la mise à jour des barres et la repeinture sont des fractions de
    milliseconde ; la marge est large pour ne pas dépendre de la charge de la machine."""

    def median_ms(self, fn, n=40):
        times = []
        for _ in range(n):
            start = time.perf_counter()
            fn()
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        return times[len(times) // 2]

    def test_sync_a_tool_click_and_the_repaint_are_far_below_a_frame(self):
        ui = self.ctl.ui
        self.rect(100, 100, 80, 50)
        names = ["select", "pen", "rect", "hand"]
        state = {"n": 0}

        def click():
            ui._tool_buttons[names[state["n"] % 4]].click()
            state["n"] += 1
            ui.sync()

        def repaint():
            for bar in ui.bars.manager.bars:
                bar.update()
            QApplication.processEvents()
        self.assertLess(self.median_ms(ui.sync), 4.0)
        self.assertLess(self.median_ms(click), 8.0)
        self.assertLess(self.median_ms(repaint), 16.0)


if __name__ == "__main__":
    unittest.main()
