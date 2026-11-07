"""Module Photoshop : BARRES FLOTTANTES (système de fm_theme, `fm_photoshop/bars.py`) — « Document » sur le Board, outils, couleurs,
brosse, calque, fichier et vue dans l'éditeur Standard ; disposition enregistrée dans `board_bars["photoshop"]` ; la barre des
modules n'est pas touchée. VRAI chemin : barre des modules -> bouton « Nouveau » -> élément -> double-clic -> éditeur."""
import os as _os, sys as _sys  # jamais les vrais réglages / presets de l'utilisateur (tests/_isolate.py)
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import _isolate  # noqa: E402,F401
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from _photoshop_case import PsCase, settle  # noqa: E402
from fm_photoshop import bars as ps_bars  # noqa: E402
from fm_photoshop.standard import TOOL_ROWS  # noqa: E402


class BarsCase(PsCase):
    def manager(self):
        return self.pane.photoshop.bars.manager

    def drag_out(self, key, x=700, y=300):
        """Ctrl + glisser (méthodes du gestionnaire) : l'élément `key` lâché dans le vide du board."""
        mgr = self.manager()
        bar = mgr.bar_of(key)
        item = bar._items[key]
        mgr.begin_item_drag(bar, item, bar.mapToGlobal(item.widget.geometry().center()))
        mgr.item_drag_to(self.pane.mapToGlobal(QPoint(x, y)))
        mgr.end_item_drag()

    def shown_titles(self):
        return [b.title() for b in self.manager().bars if b.isVisible()]


class DocumentBarTest(BarsCase):
    def test_the_module_has_a_floating_document_bar_with_its_five_buttons(self):
        self.create_via_ui()
        ctl = self.pane.photoshop
        bar = self.manager().bar("b1")
        self.assertEqual(bar.title(), "Document")
        self.assertEqual(sorted(bar.keys()), sorted(["new", "import", "layer", "standard", "export"]))
        self.assertIs(ctl.bar, bar)
        self.assertTrue(bar.isVisible())
        for key, button in ctl.buttons.items():
            self.assertIs(button.parentWidget(), bar, key)                      # des cases de la barre, plus des boutons à part
        self.assertEqual(self.shown_titles(), ["Document"])                    # rien d'autre hors de l'éditeur Standard

    def test_the_bar_is_clipped_in_the_board_area_to_the_right_of_the_module_bar(self):
        self.create_via_ui()
        pane, bar = self.pane, self.manager().bar("b1")
        self.assertTrue(pane._modulebar.isVisible())
        self.assertEqual(pane._modulebar.geometry().left(), 0)                   # la barre des modules n'a pas bougé
        self.assertEqual(bar.y(), 0)                                             # clipsée au bord haut
        self.assertGreaterEqual(bar.x(), pane.left_edge())                       # jamais sous la barre des modules

    def test_the_bar_goes_with_the_module(self):
        self.create_via_ui()
        ctl = self.pane.photoshop
        self.assertTrue(ctl.bar.isVisible())
        self.pane._modulebar.rows["photoshop"].icon.click()                      # re-clic = aucun module
        settle()
        self.assertFalse(ctl.active)
        self.assertFalse(ctl.bar.isVisible())
        self.pane._modulebar.rows["photoshop"].icon.click()
        settle()
        self.assertTrue(ctl.bar.isVisible())

    def test_a_button_dropped_in_the_void_becomes_a_bar_and_the_layout_is_saved_for_this_module_only(self):
        self.create_via_ui()
        self.drag_out("export")
        mgr = self.manager()
        new = mgr.bar_of("export")
        self.assertNotEqual(new.bar_id, "b1")
        self.assertNotIn("export", mgr.bar("b1").keys())
        saved = self.pane._settings["board_bars"]
        self.assertIn("export", next(b for b in saved["photoshop"]["bars"] if b["id"] == new.bar_id)["items"])
        self.assertNotIn("export", str(saved.get("miro", {})))                   # les autres modules gardent leur disposition

    def test_a_new_board_restores_the_saved_layout(self):
        from fm_board import ui as board_ui
        self.create_via_ui()
        self.drag_out("export")
        saved = self.pane._settings["board_bars"]
        moved = self.manager().bar_of("export").bar_id
        other = board_ui.BoardPane(self.host, {"board_bars": saved})                # autre ouverture : même disposition
        ps_bars_before = len(saved["photoshop"]["bars"])
        other.open(self.path)
        other.resize(1400, 900)
        other.show()
        other._modulebar.rows["photoshop"].icon.click()
        settle()
        try:
            mgr = other.photoshop.bars.manager
            self.assertEqual(mgr.bar_of("export").bar_id, moved)
            self.assertEqual(len(mgr.bars), ps_bars_before)
            self.assertEqual(mgr.memory["wand"][0], "t1")                           # la mémoire des places de l'éditeur est reprise aussi
        finally:
            other._autosave.stop()
            other.deleteLater()

    def test_the_buttons_still_do_their_job(self):
        self.create_via_ui()
        ctl = self.pane.photoshop
        item = self.pane.scene.board_items()[-1]
        item.setSelected(True)
        ctl.buttons["standard"].click()
        settle()
        self.assertIsNotNone(getattr(self.pane, "_photoshop_standard", None))


class StandardBarsTest(BarsCase):
    def test_every_tool_is_a_button_of_the_tools_bar_and_every_bar_is_shown(self):
        _item, std = self.editor()
        mgr = self.manager()
        tools = mgr.bar("t1")
        self.assertEqual(tools.title(), "Outils")
        self.assertEqual(sorted(tools.keys()), sorted(tool for tool, _text, _tip in TOOL_ROWS))
        self.assertEqual(set(std.tool_buttons), {tool for tool, _text, _tip in TOOL_ROWS})
        self.assertEqual(sorted(self.shown_titles()), sorted(["Outils", "Couleur", "Brosse", "Calque", "Fichier", "Vue", "Calques", "Masque"]))
        self.assertNotIn("Document", self.shown_titles())                        # « Nouveau document » n'a pas de sens ici

    def test_a_tool_button_chooses_the_tool_and_follows_the_keyboard(self):
        _item, std = self.editor()
        s = std.session
        std.tool_buttons["lasso"].click()
        self.assertEqual(s.tool, "lasso")
        self.assertTrue(std.tool_buttons["lasso"].active)
        self.assertEqual([t for t, b in std.tool_buttons.items() if b.active], ["lasso"])
        std.canvas.setFocus()
        QTest.keyClick(std.canvas, Qt.Key_E)
        self.assertEqual([t for t, b in std.tool_buttons.items() if b.active], ["eraser"])
        self.assertTrue(std.tool_buttons["eraser"].isChecked())                  # (même nom que l'ancien bouton à cocher)

    def test_brush_sliders_drive_the_brush_and_follow_it(self):
        _item, std = self.editor()
        s, panel = std.session, std.brush_panel
        brush_bar = self.manager().bar("t3")
        self.assertEqual(sorted(brush_bar.keys()), sorted(["brush_size", "brush_hardness", "brush_opacity", "brush_flow"]))
        brush_bar.item("brush_size").setValue(40)
        brush_bar.item("brush_hardness").setValue(30)
        brush_bar.item("brush_opacity").setValue(55)
        brush_bar.item("brush_flow").setValue(70)
        self.assertEqual(s.brush.size, 40)
        self.assertAlmostEqual(s.brush.hardness, 0.30)
        self.assertAlmostEqual(s.brush.opacity, 0.55)
        self.assertAlmostEqual(s.brush.flow, 0.70)
        s.brush.size = 12.0
        s.brush.opacity = 0.2
        panel.sync()                                                              # (ex. un raccourci [ ] ou une présélection)
        self.assertEqual(brush_bar.item("brush_size").value(), 12)
        self.assertEqual(brush_bar.item("brush_opacity").value(), 20)
        self.assertEqual(panel.rows["size"].field.value(), 12)                    # l'ancienne API des lignes du panneau
        std.canvas.setFocus()
        QTest.keyClick(std.canvas, Qt.Key_BracketRight)
        self.assertGreater(s.brush.size, 12)

    def test_a_brush_preset_moves_the_bar_sliders(self):
        _item, std = self.editor()
        panel = std.brush_panel
        panel.presets.setCurrentIndex(1)
        panel._preset_chosen(1)
        self.assertEqual(self.manager().bar("t3").item("brush_size").value(), round(std.session.brush.size))

    def test_the_colors_bar_shows_and_swaps_the_colors(self):
        _item, std = self.editor()
        s = std.session
        colors = self.manager().bar("t2")
        self.assertEqual(sorted(colors.keys()), ["bg", "fg", "swap"])
        s.fg, s.bg = (10, 20, 30), (200, 210, 220)
        colors.item("swap").click()
        self.assertEqual((s.fg, s.bg), ((200, 210, 220), (10, 20, 30)))
        self.assertEqual(colors.item("fg").getter(), (200, 210, 220))

    def test_layer_bar_opacity_blend_and_name(self):
        _item, std = self.editor()
        s, panel = std.session, std.layers_panel
        layer_bar = self.manager().bar("t4")
        self.assertEqual(sorted(layer_bar.keys()), ["layer_blend", "layer_name", "layer_opacity"])
        layer = s.layer()
        layer_bar.item("layer_opacity").setValue(50)
        panel.commit_live()
        self.assertAlmostEqual(layer.opacity, 0.5)
        s.undo()
        self.assertAlmostEqual(layer.opacity, 1.0)
        layer_bar.item("layer_blend").field._select("Produit")
        self.assertEqual(layer.blend, "multiply")
        s.undo()
        self.assertEqual(layer.blend, "normal")
        name = layer_bar.item("layer_name")
        self.assertEqual(name.value(), layer.name)                               # le champ montre le nom du calque
        name.field.setText("Peau")
        name.field.editingFinished.emit()
        self.assertEqual(layer.name, "Peau")
        s.undo()
        self.assertNotEqual(layer.name, "Peau")
        old = layer.name
        name.field.setText("   ")
        name.field.editingFinished.emit()
        self.assertEqual(layer.name, old)                                        # nom vide refusé
        self.assertEqual(name.value(), old)

    def test_the_layer_bar_follows_the_active_layer(self):
        _item, std = self.editor()
        s, panel = std.session, std.layers_panel
        first = s.layer()
        first.opacity, first.blend = 0.4, "screen"
        panel.add()
        second = s.layer()
        second.opacity, second.blend = 0.9, "multiply"
        settle()
        layer_bar = self.manager().bar("t4")
        self.assertEqual(layer_bar.item("layer_name").value(), second.name)
        self.assertEqual(layer_bar.item("layer_opacity").value(), 90)
        s.select_layer(first)
        settle()
        self.assertEqual(layer_bar.item("layer_opacity").value(), 40)
        self.assertEqual(layer_bar.item("layer_blend").value(), "Écran")

    def test_view_bar_zoom_fit_actual_and_display(self):
        _item, std = self.editor(zoom=2.0)
        view = self.manager().bar("t6")
        self.assertEqual(sorted(view.keys()), ["actual", "display", "fit", "zoom"])
        self.assertEqual(view.item("zoom").value(), "200")
        self.assertEqual(std.zoom_field.value_label.text(), "200")                # (compatibilité)
        view.item("zoom").field.setText("50")
        view.item("zoom").field.editingFinished.emit()
        self.assertAlmostEqual(std.canvas.zoom(), 0.5)
        view.item("actual").click()
        settle()                                                                 # (le zoom affiché est annoncé à la peinture)
        self.assertAlmostEqual(std.canvas.zoom(), 1.0)
        self.assertEqual(view.item("zoom").value(), "100")
        view.item("zoom").field.setText("abc")
        view.item("zoom").field.editingFinished.emit()
        self.assertEqual(view.item("zoom").value(), "100")                       # saisie invalide : la valeur appliquée revient
        view.item("zoom").field.setText("300")
        view.item("zoom").field.editingFinished.emit()
        settle()
        self.assertEqual(view.item("zoom").value(), "300")
        view.item("fit").click()                                                 # « Ajuster » : zoom calculé (jamais au-delà de 100 %)
        settle()
        self.assertIsNone(std.session.zoom)
        self.assertEqual(view.item("zoom").value(), str(round(std.canvas.fit_zoom() * 100)))
        view.item("display").field._select("Bilinéaire")
        self.assertEqual(std.session.display_filter, "bilinear")

    def test_file_bar_undo_redo_and_save(self):
        _item, std = self.editor()
        s, panel = std.session, std.layers_panel
        file_bar = self.manager().bar("t5")
        self.assertEqual(sorted(file_bar.keys()), sorted(["undo", "redo", "std_import", "save", "std_export"]))
        count = len(s.doc.layers)
        panel.add()
        self.assertEqual(len(s.doc.layers), count + 1)
        file_bar.item("undo").click()
        self.assertEqual(len(s.doc.layers), count)
        file_bar.item("redo").click()
        self.assertEqual(len(s.doc.layers), count + 1)
        file_bar.item("save").click()                                            # enregistre le board (fichier du test)
        settle()
        self.assertTrue(os.path.exists(self.path))

    def test_layer_and_mask_commands_are_bars_too(self):
        _item, std = self.editor()
        s, panel = std.session, std.layers_panel
        mgr = self.manager()
        layers, masks = mgr.bar("t7"), mgr.bar("t8")
        self.assertEqual((layers.title(), masks.title()), ("Calques", "Masque"))
        self.assertEqual(len(layers.keys()), 8)
        self.assertEqual(len(masks.keys()), 7)
        count = len(s.doc.layers)
        layers.item("layer_add").click()
        self.assertEqual(len(s.doc.layers), count + 1)
        layers.item("layer_duplicate").click()
        self.assertEqual(len(s.doc.layers), count + 2)
        layers.item("layer_remove").click()
        self.assertEqual(len(s.doc.layers), count + 1)
        # masque : les commandes qui ne s'appliquent pas sont grisées, la cible suit
        self.assertTrue(masks.item("mask_add").isEnabled())
        self.assertFalse(masks.item("mask_invert").isEnabled())
        self.assertFalse(masks.item("target_mask").isEnabled())
        self.assertTrue(masks.item("target_pixels").active)
        masks.item("mask_add").click()
        settle()                                                                 # (le panneau se met à jour après la notification)
        self.assertIsNotNone(s.layer().mask)
        self.assertTrue(masks.item("mask_invert").isEnabled())
        self.assertEqual(masks.item("mask_toggle").text_value(), "Désactiver")
        masks.item("target_mask").click()
        settle()
        self.assertEqual(s.target, "mask")
        self.assertTrue(masks.item("target_mask").active)
        self.assertFalse(masks.item("target_pixels").active)
        masks.item("mask_remove").click()
        settle()
        self.assertIsNone(s.layer().mask)
        self.assertEqual(s.target, "pixels")
        self.assertEqual(masks.item("mask_toggle").text_value(), "Activer")

    def test_the_bars_are_above_the_editor_and_clipped_to_the_canvas(self):
        _item, std = self.editor()
        mgr = self.manager()
        children = self.pane.children()
        area = std.bars_area()
        self.assertGreater(area.width(), 300)
        self.assertLess(area.right(), std.geometry().right())                    # l'établi s'arrête avant les panneaux de droite
        for bar in (b for b in mgr.bars if b.bar_id != "b1"):                    # (« Document » : seulement sur le Board)
            self.assertTrue(bar.isVisible(), bar.title())
            self.assertGreater(children.index(bar), children.index(std), bar.title())        # au-dessus de l'éditeur plein cadre
            rect = bar.geometry()
            self.assertTrue(area.adjusted(-1, -1, 1, 1).contains(rect), (bar.title(), rect, area))
        tools, colors = mgr.bar("t1"), mgr.bar("t2")
        self.assertEqual(tools.x(), area.x())                                    # « Outils » clipsée à gauche de l'établi
        self.assertEqual(colors.y(), tools.y() + tools.height())                 # « Couleur » collée derrière « Outils »

    def test_the_default_bars_do_not_overlap(self):
        self.pane.resize(1400, 900)
        _item, std = self.editor()
        shown = [b for b in self.manager().bars if b.isVisible()]
        for i, a in enumerate(shown):
            for b in shown[i + 1:]:
                self.assertFalse(a.geometry().intersects(b.geometry()), (a.title(), b.title(), a.geometry(), b.geometry()))

    def test_closing_the_editor_removes_its_bars_and_reopening_restores_the_places(self):
        item, std = self.editor()
        mgr = self.manager()
        self.drag_out("wand")
        moved = mgr.bar_of("wand").bar_id
        self.assertNotIn(moved, ("t1",))
        std.back.click()
        settle()
        self.assertIsNone(getattr(self.pane, "_photoshop_standard", None))
        self.assertEqual(self.shown_titles(), ["Document"])                      # de retour sur le Board
        self.assertNotIn("wand", [k for b in mgr.bars for k in b.keys()])        # ses éléments ont disparu avec la session
        std2 = self.open_standard_by_double_click(item)
        self.assertIsNotNone(std2)
        self.assertEqual(mgr.bar_of("wand").bar_id, moved)                       # l'outil retrouve la barre que l'utilisateur lui avait donnée
        self.assertNotIn("wand", mgr.bar("t1").keys())
        self.assertIs(mgr.bar_of("wand").item("wand"), std2.tool_buttons["wand"])  # (un nouveau bouton, lié à la nouvelle session)

    def test_places_are_saved_with_the_layout_and_survive_a_new_board(self):
        item, std = self.editor()
        self.drag_out("heal")
        moved = self.manager().bar_of("heal").bar_id
        saved = self.pane._settings["board_bars"]["photoshop"]
        self.assertEqual(saved["memory"]["heal"][0], moved)
        std.back.click()
        settle()
        self.assertEqual(self.pane._settings["board_bars"]["photoshop"]["memory"]["heal"][0], moved)   # retenue après fermeture

    def test_a_bar_emptied_by_the_user_comes_back_with_its_default_elements_next_time(self):
        item, std = self.editor()
        mgr = self.manager()
        for index, key in enumerate(list(mgr.bar("t6").keys())):
            self.drag_out(key, 600, 150 + 130 * index)                           # chacun dans un vide différent : une barre chacun
        self.assertIsNone(mgr.bar("t6"))                                         # barre vidée : supprimée
        std.back.click()
        settle()
        std2 = self.open_standard_by_double_click(item)
        self.assertIsNotNone(std2)
        self.assertTrue(all(mgr.bar_of(key) is not None for key in ("zoom", "fit", "actual", "display")))

    def test_the_editor_opens_without_the_module_chosen_and_the_bars_leave_with_it(self):
        item, std = self.editor()
        std.back.click()
        settle()
        self.pane._modulebar.rows["photoshop"].icon.click()                      # aucun module
        settle()
        self.assertFalse(self.pane.photoshop.active)
        std2 = self.open_standard_by_double_click(item)
        self.assertIsNotNone(std2)
        self.assertEqual(sorted(self.shown_titles()), sorted(["Outils", "Couleur", "Brosse", "Calque", "Fichier", "Vue", "Calques", "Masque"]))
        std2.back.click()
        settle()
        self.assertEqual(self.shown_titles(), [])

    def test_resizing_the_board_keeps_the_bars_in_the_canvas(self):
        _item, std = self.editor()
        self.pane.resize(1100, 760)
        self.host.resize(1100, 760)
        settle(0.1)
        area = std.bars_area()
        for bar in self.manager().bars:
            self.assertTrue(area.adjusted(-1, -1, 1, 1).contains(bar.geometry()), (bar.title(), bar.geometry(), area))

    def test_the_look_comes_from_the_theme_and_changes_with_it(self):
        from fm_theme import palette
        _item, std = self.editor()
        tools = self.manager().bar("t1")
        palette.restyle_palettes_in(self.pane, {"palette_cell_size": 44})
        try:
            self.assertEqual(tools.item("brush").width(), 44)                    # cases de la barre = réglage « palette_cell_size »
        finally:
            palette.restyle_palettes_in(self.pane, {})


class GlyphTest(unittest.TestCase):
    def test_every_tool_has_its_own_icon(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QImage, QPainter
        seen = set()
        for tool, _text, _tip in TOOL_ROWS:
            image = QImage(48, 48, QImage.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            ps_bars.paint_tool(painter, tool, QRectF(8, 8, 32, 32), QColor("#ffffff"))
            painter.end()
            ink = sum(1 for y in range(48) for x in range(48) if image.pixelColor(x, y).alpha() > 0)
            self.assertGreater(ink, 20, tool)                                    # quelque chose est dessiné
            seen.add(bytes(image.constBits()))
        self.assertEqual(len(seen), len(TOOL_ROWS))                              # et deux outils n'ont pas la même icône


class DefaultStateTest(unittest.TestCase):
    def test_the_default_state_names_every_tool_and_control(self):
        state = ps_bars.photoshop_default_state()
        self.assertEqual([b["id"] for b in state["bars"]], ["b1", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"])
        memory = state["memory"]
        for tool, _text, _tip in TOOL_ROWS:
            self.assertEqual(memory[tool][0], "t1", tool)
        self.assertEqual({k for k, v in memory.items() if v[0] == "t3"},
                         {"brush_size", "brush_hardness", "brush_opacity", "brush_flow"})
        self.assertEqual(set(ps_bars.TOOL_KEYS), {tool for tool, _text, _tip in TOOL_ROWS})
        cells = [tuple(v[:3]) for k, v in memory.items() if v[0] == "t1"]
        self.assertEqual(len(cells), len(set(cells)))                            # chaque outil dans sa case


if __name__ == "__main__":
    unittest.main()
